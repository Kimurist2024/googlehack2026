"""データの置き場所。手元ではメモリ、本番では Firestore を使う。

どちらも同じ操作を持つ。受け取る値と返す値はコピーなので、書き込みの呼び忘れは手元のテストでも見つかる。
"""
import copy
import os
import threading
from dataclasses import dataclass, replace
from typing import Any, Protocol

Doc = dict[str, Any]

# 進み具合は状態ごとの件数で返すので、提出の状態はここに挙げたものだけにする
SUBMISSION_STATUSES = ("queued", "ready", "excluded", "failed")


@dataclass
class ClassRecord:
    id: str
    name: str
    teacher: str
    student_numbers: dict[str, str]  # student_id -> 出席番号
    open_assignment_id: str | None = None  # 受付中の課題は1クラスに1つだけ


@dataclass
class AssignmentRecord:
    id: str
    class_id: str
    title: str
    learning_goal: str
    stdin_examples: list[str]
    time_limit_sec: int
    question_count: int
    weights: dict[str, float]
    state: str = "draft"  # draft, generating, ready, open, closed
    generating_since: float | None = None
    # この時刻を過ぎたら、課題と生徒のデータ（提出、問い、正解、解答、声かけ）はないものとして扱う。
    # Firestore では各文書に同じ時刻を書き、TTL で消す。作成時に決めて変えない
    expire_at: float | None = None


def is_expired(assignment: AssignmentRecord, now: float) -> bool:
    return assignment.expire_at is not None and now >= assignment.expire_at


def can_add_submissions(assignment: AssignmentRecord) -> bool:
    return assignment.state in ("draft", "ready")


def can_begin_generation(assignment: AssignmentRecord, now: float, stale_after: float) -> bool:
    if assignment.state in ("draft", "ready"):
        return True
    # 処理中のインスタンスが落ちると「生成中」のまま残るので、時間が経ったらやり直せるようにする
    return assignment.state == "generating" and now - (assignment.generating_since or 0) > stale_after


class Store(Protocol):
    def create_class(self, classroom: ClassRecord, class_code_hash: str, credentials: dict[str, str]) -> None:
        """credentials は個人コードのハッシュ -> student_id。"""

    def get_class(self, class_id: str) -> ClassRecord | None: ...

    def class_id_for_code(self, code_hash: str) -> str | None: ...

    def student_for_credential(self, class_id: str, code_hash: str) -> str | None: ...

    def create_assignment(self, assignment: AssignmentRecord) -> None: ...

    def get_assignment(self, assignment_id: str) -> AssignmentRecord | None: ...

    def add_submissions(self, assignment_id: str, codes: dict[str, str]) -> bool:
        """提出を登録し、課題を draft に戻す。受付を始めた課題なら何もせず False を返す。"""

    def begin_generation(self, assignment_id: str, now: float, stale_after: float) -> bool:
        """generating に進める。同時に呼ばれても True を返すのは1回だけ。"""

    def end_generation(self, assignment_id: str, state: str) -> None: ...

    def open_assignment(self, assignment_id: str) -> bool:
        """ready の課題を受付中にする。同じクラスに受付中の課題があれば False を返す。"""

    def close_assignment(self, assignment_id: str) -> bool:
        """受付中の課題を締め切る。受付中でなければ False を返す。"""

    def submissions(self, assignment_id: str) -> dict[str, Doc]:
        """提出をコードごと返す。"""

    def submission_statuses(self, assignment_id: str) -> dict[str, Doc]:
        """提出の状態と理由だけを返す。コードは含めない。"""

    def submission_counts(self, assignment_id: str) -> dict[str, int]:
        """状態ごとの件数を返す。0件の状態は含めない。"""

    def save_generation_result(
        self, assignment_id: str, student_id: str, status: str, reason: str | None, quiz: Doc | None, answer_key: Doc | None
    ) -> None:
        """生成の結果を書く。問いを作れなかった生徒には、前回の問いも残さない。"""

    def get_quiz(self, assignment_id: str, student_id: str) -> Doc | None: ...

    def get_answer_key(self, assignment_id: str, student_id: str) -> Doc | None: ...

    def start_attempt(self, assignment_id: str, student_id: str, started_at: float) -> Doc:
        """解答を始める。すでに始めていれば、最初の記録をそのまま返す。"""

    def get_attempt(self, assignment_id: str, student_id: str) -> Doc | None: ...

    def finish_attempt(self, assignment_id: str, student_id: str, graded: list[Doc], submitted_at: float, extra: Doc | None = None) -> bool:
        """採点結果を書く。同時に呼ばれても True を返すのは1回だけ。extra はオフライン提出などの印。"""

    def attempts(self, assignment_id: str) -> dict[str, Doc]: ...

    def followups(self, assignment_id: str) -> dict[str, Doc]: ...

    def add_followup_question(self, assignment_id: str, student_id: str, question: str, line: int | None) -> None: ...

    def record_action(self, assignment_id: str, student_id: str, action: Doc) -> None: ...

    def login_failures(self, client_key: str, window: int) -> int:
        """その接続元の、その1分間の入室の失敗の回数。インスタンスをまたいで数える。"""

    def add_login_failure(self, client_key: str, window: int, expire_at: float) -> None:
        """入室の失敗を1回数える。expire_at を過ぎた記録は消してよい。"""

    def save_offline_verifiers(self, class_id: str, verifiers: Doc) -> None:
        """授業パッケージに入れる、コードの照合値（scrypt）を保存する。app/classpack.py を参照。"""

    def offline_verifiers(self, class_id: str) -> Doc | None: ...

    def delete_assignment(self, assignment_id: str) -> None:
        """課題と、その生徒のデータをすべて消す。受付中なら、クラスの受付中の印も外す。"""

    def delete_class(self, class_id: str) -> None:
        """クラス、授業コードと個人コードの対応、クラスのすべての課題を消す。授業コードから先に消す。"""


class MemoryStore:
    """手元の開発とテスト用。再起動で消え、複数のインスタンスでは共有できない。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._classes: dict[str, ClassRecord] = {}
        self._class_codes: dict[str, str] = {}
        self._credentials: dict[tuple[str, str], str] = {}
        self._assignments: dict[str, AssignmentRecord] = {}
        self._submissions: dict[str, dict[str, Doc]] = {}
        self._quizzes: dict[str, dict[str, Doc]] = {}
        self._answer_keys: dict[str, dict[str, Doc]] = {}
        self._attempts: dict[str, dict[str, Doc]] = {}
        self._followups: dict[str, dict[str, Doc]] = {}
        self._login_failures: dict[tuple[str, int], int] = {}
        self._offline_verifiers: dict[str, Doc] = {}

    def create_class(self, classroom: ClassRecord, class_code_hash: str, credentials: dict[str, str]) -> None:
        with self._lock:
            self._classes[classroom.id] = copy.deepcopy(classroom)
            self._class_codes[class_code_hash] = classroom.id
            for code_hash, student_id in credentials.items():
                self._credentials[(classroom.id, code_hash)] = student_id

    def get_class(self, class_id: str) -> ClassRecord | None:
        with self._lock:
            return copy.deepcopy(self._classes.get(class_id))

    def class_id_for_code(self, code_hash: str) -> str | None:
        with self._lock:
            return self._class_codes.get(code_hash)

    def student_for_credential(self, class_id: str, code_hash: str) -> str | None:
        with self._lock:
            return self._credentials.get((class_id, code_hash))

    def create_assignment(self, assignment: AssignmentRecord) -> None:
        with self._lock:
            self._assignments[assignment.id] = copy.deepcopy(assignment)
            for table in (self._submissions, self._quizzes, self._answer_keys, self._attempts, self._followups):
                table[assignment.id] = {}

    def get_assignment(self, assignment_id: str) -> AssignmentRecord | None:
        with self._lock:
            return copy.deepcopy(self._assignments.get(assignment_id))

    def add_submissions(self, assignment_id: str, codes: dict[str, str]) -> bool:
        with self._lock:
            assignment = self._assignments[assignment_id]
            if not can_add_submissions(assignment):
                return False
            for student_id, code in codes.items():
                self._submissions[assignment_id][student_id] = {"code": code, "status": "queued", "reason": None}
            self._assignments[assignment_id] = replace(assignment, state="draft")
            return True

    def begin_generation(self, assignment_id: str, now: float, stale_after: float) -> bool:
        with self._lock:
            assignment = self._assignments[assignment_id]
            if not can_begin_generation(assignment, now, stale_after):
                return False
            self._assignments[assignment_id] = replace(assignment, state="generating", generating_since=now)
            return True

    def end_generation(self, assignment_id: str, state: str) -> None:
        with self._lock:
            self._assignments[assignment_id] = replace(self._assignments[assignment_id], state=state, generating_since=None)

    def open_assignment(self, assignment_id: str) -> bool:
        with self._lock:
            assignment = self._assignments[assignment_id]
            classroom = self._classes[assignment.class_id]
            if assignment.state != "ready" or classroom.open_assignment_id is not None:
                return False
            self._assignments[assignment_id] = replace(assignment, state="open")
            self._classes[assignment.class_id] = replace(classroom, open_assignment_id=assignment_id)
            return True

    def close_assignment(self, assignment_id: str) -> bool:
        with self._lock:
            assignment = self._assignments[assignment_id]
            if assignment.state != "open":
                return False
            self._assignments[assignment_id] = replace(assignment, state="closed")
            self._classes[assignment.class_id] = replace(self._classes[assignment.class_id], open_assignment_id=None)
            return True

    def submissions(self, assignment_id: str) -> dict[str, Doc]:
        with self._lock:
            return copy.deepcopy(self._submissions[assignment_id])

    def submission_statuses(self, assignment_id: str) -> dict[str, Doc]:
        with self._lock:
            return {
                student_id: {"status": doc["status"], "reason": doc["reason"]}
                for student_id, doc in self._submissions[assignment_id].items()
            }

    def submission_counts(self, assignment_id: str) -> dict[str, int]:
        with self._lock:
            docs = self._submissions[assignment_id].values()
            counts = {status: sum(1 for doc in docs if doc["status"] == status) for status in SUBMISSION_STATUSES}
        return {status: count for status, count in counts.items() if count}

    def save_generation_result(
        self, assignment_id: str, student_id: str, status: str, reason: str | None, quiz: Doc | None, answer_key: Doc | None
    ) -> None:
        with self._lock:
            self._submissions[assignment_id][student_id].update(status=status, reason=reason)
            if quiz is None or answer_key is None:
                self._quizzes[assignment_id].pop(student_id, None)
                self._answer_keys[assignment_id].pop(student_id, None)
            else:
                self._quizzes[assignment_id][student_id] = copy.deepcopy(quiz)
                self._answer_keys[assignment_id][student_id] = copy.deepcopy(answer_key)

    def get_quiz(self, assignment_id: str, student_id: str) -> Doc | None:
        with self._lock:
            return copy.deepcopy(self._quizzes[assignment_id].get(student_id))

    def get_answer_key(self, assignment_id: str, student_id: str) -> Doc | None:
        with self._lock:
            return copy.deepcopy(self._answer_keys[assignment_id].get(student_id))

    def start_attempt(self, assignment_id: str, student_id: str, started_at: float) -> Doc:
        with self._lock:
            attempt = self._attempts[assignment_id].setdefault(student_id, {"started_at": started_at, "submitted_at": None, "graded": []})
            return copy.deepcopy(attempt)

    def get_attempt(self, assignment_id: str, student_id: str) -> Doc | None:
        with self._lock:
            return copy.deepcopy(self._attempts[assignment_id].get(student_id))

    def finish_attempt(self, assignment_id: str, student_id: str, graded: list[Doc], submitted_at: float, extra: Doc | None = None) -> bool:
        with self._lock:
            attempt = self._attempts[assignment_id].get(student_id)
            if attempt is None or attempt["submitted_at"] is not None:
                return False
            attempt.update(copy.deepcopy(extra or {}), graded=copy.deepcopy(graded), submitted_at=submitted_at)
            return True

    def attempts(self, assignment_id: str) -> dict[str, Doc]:
        with self._lock:
            return copy.deepcopy(self._attempts[assignment_id])

    def followups(self, assignment_id: str) -> dict[str, Doc]:
        with self._lock:
            return copy.deepcopy(self._followups[assignment_id])

    def add_followup_question(self, assignment_id: str, student_id: str, question: str, line: int | None) -> None:
        with self._lock:
            self._followups[assignment_id].setdefault(student_id, {}).update(question=question, line=line)

    def record_action(self, assignment_id: str, student_id: str, action: Doc) -> None:
        with self._lock:
            self._followups[assignment_id].setdefault(student_id, {}).update(copy.deepcopy(action))

    def login_failures(self, client_key: str, window: int) -> int:
        with self._lock:
            return self._login_failures.get((client_key, window), 0)

    def delete_assignment(self, assignment_id: str) -> None:
        with self._lock:
            assignment = self._assignments.pop(assignment_id, None)
            for table in (self._submissions, self._quizzes, self._answer_keys, self._attempts, self._followups):
                table.pop(assignment_id, None)
            classroom = self._classes.get(assignment.class_id) if assignment else None
            if classroom is not None and classroom.open_assignment_id == assignment_id:
                self._classes[classroom.id] = replace(classroom, open_assignment_id=None)

    def save_offline_verifiers(self, class_id: str, verifiers: Doc) -> None:
        with self._lock:
            self._offline_verifiers[class_id] = copy.deepcopy(verifiers)

    def offline_verifiers(self, class_id: str) -> Doc | None:
        with self._lock:
            return copy.deepcopy(self._offline_verifiers.get(class_id))

    def delete_class(self, class_id: str) -> None:
        with self._lock:
            self._offline_verifiers.pop(class_id, None)
            for code_hash in [code_hash for code_hash, owner in self._class_codes.items() if owner == class_id]:
                del self._class_codes[code_hash]
            for key in [key for key in self._credentials if key[0] == class_id]:
                del self._credentials[key]
            for assignment_id in [aid for aid, assignment in self._assignments.items() if assignment.class_id == class_id]:
                self.delete_assignment(assignment_id)
            self._classes.pop(class_id, None)

    def add_login_failure(self, client_key: str, window: int, expire_at: float) -> None:
        with self._lock:
            # 古い時間帯の記録は残しておく意味がないので、ここで捨てる
            for key in [key for key in self._login_failures if key[1] < window - 1]:
                del self._login_failures[key]
            self._login_failures[(client_key, window)] = self._login_failures.get((client_key, window), 0) + 1


def default_store() -> Store:
    """環境変数から選ぶ。指定がなければ本番用の Firestore を使う。"""
    if os.environ.get("DEPLOY_MODE") == "lan":
        # 校内LAN版は外とつながらないので、教員PCの暗号化したファイルに置く
        from .lan_store import LanStore

        return LanStore.open_default()
    if os.environ.get("STORE_BACKEND", "firestore") == "memory":
        return MemoryStore()
    from .firestore_store import FirestoreStore

    return FirestoreStore()
