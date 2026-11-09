"""Firestore に置く本番用のデータの置き場所。

classes/{id}                          クラスと名簿（出席番号）、受付中の課題
classes/{id}/credentials/{hash}       個人コードのハッシュ -> student_id
classes/{id}/students/{sid}           生徒ごとの記録（課題ごとの結果、説明を聞いた行、教員の処置）
classCodes/{hash}                     授業コードのハッシュ -> class_id
assignments/{id}                      課題                         ┐
assignments/{id}/submissions/{sid}    提出のコードと状態           │ どれも課題と同じ expire_at を持ち、
assignments/{id}/quizzes/{sid}        問い（正解なし）             │ Firestore の TTL で消える。
assignments/{id}/answerKeys/{sid}     正解、解説、実行の記録       │ TTL は親を消しても子を消さないので、
assignments/{id}/attempts/{sid}       開始と提出の時刻、採点結果   │ 1つずつに印を付ける
assignments/{id}/followups/{sid}      教員に渡す質問案と処置       ┘
loginFailures/{client}-{window}       接続元（鍵付きハッシュ）ごとの1分間の入室の失敗。expire_at で TTL 削除

生徒ごとの記録（classes/{id}/students/{sid}）は課題をまたいで残すので、記録の1件ずつに元の課題の expire_at を持たせ、
読むときと書くときに期限の過ぎたものを外す。文書の expire_at は最後まで残る記録の期限にし、TTL で消す。

ブラウザからは読み書きさせない（firestore.rules）。サーバーの権限でAPIだけが触る。
TTL の削除は期限から遅れることがあるので、期限を過ぎた課題はアプリの側でもないものとして扱う（app/main.py）。
"""
import os
import random
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable

from google.api_core.exceptions import Aborted
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .store import SUBMISSION_STATUSES, AssignmentRecord, ClassRecord, Doc, can_add_submissions, can_begin_generation, live_entries, merged_entries, record_expire_at


MAX_TRANSACTION_ATTEMPTS = 10


def _timestamp(seconds: float | None) -> datetime | None:
    # TTL の対象にできるのはタイムスタンプ型の項目だけなので、数値では保存しない
    return None if seconds is None else datetime.fromtimestamp(seconds, tz=timezone.utc)


def _assignment_fields(assignment: AssignmentRecord) -> Doc:
    fields = {key: value for key, value in asdict(assignment).items() if key != "id"}
    fields["expire_at"] = _timestamp(assignment.expire_at)
    return fields


def _assignment_record(snapshot) -> AssignmentRecord:
    data = snapshot.to_dict()
    expire_at = data.get("expire_at")
    data["expire_at"] = expire_at.timestamp() if isinstance(expire_at, datetime) else expire_at
    return AssignmentRecord(id=snapshot.id, **data)


def _class_fields(classroom: ClassRecord) -> Doc:
    # map はキーの順に並び替えられてしまうので、名簿の順を保てる配列で持つ
    roster = [{"student_id": student_id, "number": number} for student_id, number in classroom.student_numbers.items()]
    return {"name": classroom.name, "teacher": classroom.teacher, "roster": roster, "open_assignment_id": classroom.open_assignment_id}


def _class_record(snapshot) -> ClassRecord:
    data = snapshot.to_dict()
    return ClassRecord(
        id=snapshot.id,
        name=data["name"],
        teacher=data["teacher"],
        student_numbers={entry["student_id"]: entry["number"] for entry in data["roster"]},
        open_assignment_id=data["open_assignment_id"],
    )


class FirestoreStore:
    def __init__(self, project: str | None = None) -> None:
        self.db = firestore.Client(project=project or os.environ.get("GOOGLE_CLOUD_PROJECT"))
        # 課題の期限は作成時に決めて変えないので、読んだ値を覚えておいてよい
        self._expiry_cache: dict[str, datetime | None] = {}

    def _expiry(self, assignment_id: str) -> Doc:
        """生徒のデータの文書に付ける期限。課題に期限がなければ何も付けない。"""
        if assignment_id not in self._expiry_cache:
            snapshot = self._assignment(assignment_id).get(["expire_at"])
            self._expiry_cache[assignment_id] = (snapshot.to_dict() or {}).get("expire_at") if snapshot.exists else None
        expire_at = self._expiry_cache[assignment_id]
        return {"expire_at": expire_at} if expire_at is not None else {}

    def _class(self, class_id: str):
        return self.db.collection("classes").document(class_id)

    def _assignment(self, assignment_id: str):
        return self.db.collection("assignments").document(assignment_id)

    def _part(self, assignment_id: str, name: str):
        return self._assignment(assignment_id).collection(name)

    def _in_transaction(self, work: Callable[[Any], Any]) -> Any:
        # 競合すると work ごとやり直す。読み取りは書き込みより先に行う。
        # SDK の再試行は間を置かず、同じ相手とまた衝突しやすいので、少しずらして自前で試す
        for attempt in range(1, MAX_TRANSACTION_ATTEMPTS + 1):
            try:
                return firestore.transactional(work)(self.db.transaction(max_attempts=1))
            except (Aborted, ValueError) as error:
                conflicted = isinstance(error, Aborted) or isinstance(error.__cause__, Aborted)
                if not conflicted or attempt == MAX_TRANSACTION_ATTEMPTS:
                    raise
            time.sleep(random.uniform(0, 0.1 * attempt))

    def _read_assignment(self, transaction, assignment_id: str) -> AssignmentRecord:
        return _assignment_record(self._assignment(assignment_id).get(transaction=transaction))

    def _doc(self, assignment_id: str, name: str, student_id: str) -> Doc | None:
        return self._part(assignment_id, name).document(student_id).get().to_dict()

    def _all(self, assignment_id: str, name: str) -> dict[str, Doc]:
        return {snapshot.id: snapshot.to_dict() for snapshot in self._part(assignment_id, name).stream()}

    def create_class(self, classroom: ClassRecord, class_code_hash: str, credentials: dict[str, str]) -> None:
        reference = self._class(classroom.id)
        batch = self.db.batch()
        batch.set(reference, _class_fields(classroom))
        batch.set(self.db.collection("classCodes").document(class_code_hash), {"class_id": classroom.id})
        for code_hash, student_id in credentials.items():
            batch.set(reference.collection("credentials").document(code_hash), {"student_id": student_id})
        batch.commit()

    def get_class(self, class_id: str) -> ClassRecord | None:
        snapshot = self._class(class_id).get()
        return _class_record(snapshot) if snapshot.exists else None

    def class_id_for_code(self, code_hash: str) -> str | None:
        snapshot = self.db.collection("classCodes").document(code_hash).get()
        return snapshot.get("class_id") if snapshot.exists else None

    def student_for_credential(self, class_id: str, code_hash: str) -> str | None:
        snapshot = self._class(class_id).collection("credentials").document(code_hash).get()
        return snapshot.get("student_id") if snapshot.exists else None

    def create_assignment(self, assignment: AssignmentRecord) -> None:
        self._assignment(assignment.id).set(_assignment_fields(assignment))

    def get_assignment(self, assignment_id: str) -> AssignmentRecord | None:
        snapshot = self._assignment(assignment_id).get()
        return _assignment_record(snapshot) if snapshot.exists else None

    def add_submissions(self, assignment_id: str, codes: dict[str, str]) -> bool:
        def work(transaction) -> bool:
            assignment = self._read_assignment(transaction, assignment_id)
            if not can_add_submissions(assignment):
                return False
            expiry = {"expire_at": _timestamp(assignment.expire_at)} if assignment.expire_at is not None else {}
            for student_id, code in codes.items():
                reference = self._part(assignment_id, "submissions").document(student_id)
                transaction.set(reference, {"code": code, "status": "queued", "reason": None, **expiry})
            transaction.update(self._assignment(assignment_id), {"state": "draft"})
            return True

        return self._in_transaction(work)

    def begin_generation(self, assignment_id: str, now: float, stale_after: float) -> bool:
        def work(transaction) -> bool:
            if not can_begin_generation(self._read_assignment(transaction, assignment_id), now, stale_after):
                return False
            transaction.update(self._assignment(assignment_id), {"state": "generating", "generating_since": now})
            return True

        return self._in_transaction(work)

    def end_generation(self, assignment_id: str, state: str) -> None:
        self._assignment(assignment_id).update({"state": state, "generating_since": None})

    def open_assignment(self, assignment_id: str) -> bool:
        def work(transaction) -> bool:
            assignment = self._read_assignment(transaction, assignment_id)
            class_reference = self._class(assignment.class_id)
            classroom = class_reference.get(transaction=transaction)
            if assignment.state != "ready" or classroom.get("open_assignment_id") is not None:
                return False
            transaction.update(self._assignment(assignment_id), {"state": "open"})
            transaction.update(class_reference, {"open_assignment_id": assignment_id})
            return True

        return self._in_transaction(work)

    def close_assignment(self, assignment_id: str) -> bool:
        def work(transaction) -> bool:
            assignment = self._read_assignment(transaction, assignment_id)
            if assignment.state != "open":
                return False
            transaction.update(self._assignment(assignment_id), {"state": "closed"})
            transaction.update(self._class(assignment.class_id), {"open_assignment_id": None})
            return True

        return self._in_transaction(work)

    def submissions(self, assignment_id: str) -> dict[str, Doc]:
        return self._all(assignment_id, "submissions")

    def submission_statuses(self, assignment_id: str) -> dict[str, Doc]:
        snapshots = self._part(assignment_id, "submissions").select(["status", "reason"]).stream()
        return {snapshot.id: snapshot.to_dict() for snapshot in snapshots}

    def submission_counts(self, assignment_id: str) -> dict[str, int]:
        # 画面が生成中に何度も聞くので、提出を1件ずつ読まずに集計で数える
        counts = {}
        for status in SUBMISSION_STATUSES:
            query = self._part(assignment_id, "submissions").where(filter=FieldFilter("status", "==", status))
            count = int(query.count().get()[0][0].value)
            if count:
                counts[status] = count
        return counts

    def save_generation_result(
        self, assignment_id: str, student_id: str, status: str, reason: str | None, quiz: Doc | None, answer_key: Doc | None
    ) -> None:
        quiz_reference = self._part(assignment_id, "quizzes").document(student_id)
        key_reference = self._part(assignment_id, "answerKeys").document(student_id)
        batch = self.db.batch()
        batch.update(self._part(assignment_id, "submissions").document(student_id), {"status": status, "reason": reason})
        if quiz is None or answer_key is None:
            batch.delete(quiz_reference)
            batch.delete(key_reference)
        else:
            expiry = self._expiry(assignment_id)
            batch.set(quiz_reference, {**quiz, **expiry})
            batch.set(key_reference, {**answer_key, **expiry})
        batch.commit()

    def get_quiz(self, assignment_id: str, student_id: str) -> Doc | None:
        return self._doc(assignment_id, "quizzes", student_id)

    def get_answer_key(self, assignment_id: str, student_id: str) -> Doc | None:
        return self._doc(assignment_id, "answerKeys", student_id)

    def start_attempt(self, assignment_id: str, student_id: str, started_at: float) -> Doc:
        reference = self._part(assignment_id, "attempts").document(student_id)
        expiry = self._expiry(assignment_id)

        def work(transaction) -> Doc:
            snapshot = reference.get(transaction=transaction)
            if snapshot.exists:
                return snapshot.to_dict()
            attempt = {"started_at": started_at, "submitted_at": None, "graded": []}
            transaction.create(reference, {**attempt, **expiry})
            return attempt

        return self._in_transaction(work)

    def get_attempt(self, assignment_id: str, student_id: str) -> Doc | None:
        return self._doc(assignment_id, "attempts", student_id)

    def finish_attempt(self, assignment_id: str, student_id: str, graded: list[Doc], submitted_at: float, extra: Doc | None = None) -> bool:
        reference = self._part(assignment_id, "attempts").document(student_id)

        def work(transaction) -> bool:
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists or snapshot.get("submitted_at") is not None:
                return False
            transaction.update(reference, {**(extra or {}), "graded": graded, "submitted_at": submitted_at})
            return True

        return self._in_transaction(work)

    def attempts(self, assignment_id: str) -> dict[str, Doc]:
        return self._all(assignment_id, "attempts")

    def use_chat_turn(self, assignment_id: str, student_id: str, limit: int) -> int | None:
        reference = self._part(assignment_id, "attempts").document(student_id)

        def work(transaction) -> int | None:
            snapshot = reference.get(transaction=transaction)
            used = (snapshot.to_dict() or {}).get("chat_used", 0) if snapshot.exists else limit
            if used >= limit:
                return None
            transaction.update(reference, {"chat_used": used + 1})
            return limit - used - 1

        return self._in_transaction(work)

    def save_explanation(self, assignment_id: str, student_id: str, line: int, text: str) -> bool:
        reference = self._part(assignment_id, "attempts").document(student_id)

        def work(transaction) -> bool:
            snapshot = reference.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else None
            if data is None or data.get("submitted_at") is None:
                return False
            # 行番号を項目名にすると数字で始まる名前になるので、map ごと書き直す
            explanations = {**(data.get("explanations") or {}), str(line): text}
            transaction.update(reference, {"explanations": explanations})
            return True

        return self._in_transaction(work)

    def save_explanation_checks(self, assignment_id: str, student_id: str, line: int, text: str, checks: list[Doc]) -> None:
        reference = self._part(assignment_id, "attempts").document(student_id)

        def work(transaction) -> None:
            snapshot = reference.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else None
            if data is None or (data.get("explanations") or {}).get(str(line)) != text:
                return
            saved = {**(data.get("explanation_checks") or {}), str(line): {"text": text, "checks": checks}}
            transaction.update(reference, {"explanation_checks": saved})

        self._in_transaction(work)

    def followups(self, assignment_id: str) -> dict[str, Doc]:
        return self._all(assignment_id, "followups")

    def add_followup(self, assignment_id: str, student_id: str, question: str, line: int | None, review: Doc | None) -> None:
        fields = {"question": question, "line": line, "review": review, **self._expiry(assignment_id)}
        self._part(assignment_id, "followups").document(student_id).set(fields, merge=True)

    def record_action(self, assignment_id: str, student_id: str, action: Doc) -> None:
        self._part(assignment_id, "followups").document(student_id).set({**action, **self._expiry(assignment_id)}, merge=True)

    def set_class_summary(self, assignment_id: str, summary: Doc) -> None:
        self._assignment(assignment_id).update({"class_summary": summary})

    def _record(self, class_id: str, student_id: str):
        return self._class(class_id).collection("students").document(student_id)

    def get_student_record(self, class_id: str, student_id: str) -> Doc | None:
        data = self._record(class_id, student_id).get().to_dict()
        if data is None:
            return None
        return {"entries": live_entries(data.get("entries", []), time.time())}

    @staticmethod
    def _record_fields(entries: list[Doc]) -> Doc:
        expire_at = record_expire_at(entries)
        return {"entries": entries, "expire_at": _timestamp(expire_at)} if expire_at is not None else {"entries": entries}

    def save_student_entry(self, class_id: str, student_id: str, entry: Doc) -> None:
        reference = self._record(class_id, student_id)

        def work(transaction) -> None:
            snapshot = reference.get(transaction=transaction)
            entries = (snapshot.to_dict() or {}).get("entries", []) if snapshot.exists else []
            transaction.set(reference, self._record_fields(merged_entries(entries, entry)))

        self._in_transaction(work)

    def set_entry_action(self, class_id: str, student_id: str, assignment_id: str, action: Doc) -> None:
        reference = self._record(class_id, student_id)

        def work(transaction) -> None:
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                return
            entries = (snapshot.to_dict() or {}).get("entries", [])
            if not any(entry["assignment_id"] == assignment_id for entry in entries):
                return
            for entry in entries:
                if entry["assignment_id"] == assignment_id:
                    entry["action"] = action
            transaction.update(reference, {"entries": entries})

        self._in_transaction(work)

    def remove_entries(self, class_id: str, assignment_id: str) -> None:
        for snapshot in self._class(class_id).collection("students").stream():
            reference = snapshot.reference

            def work(transaction, reference=reference) -> None:
                current = reference.get(transaction=transaction)
                if not current.exists:
                    return
                entries = (current.to_dict() or {}).get("entries", [])
                kept = [entry for entry in entries if entry["assignment_id"] != assignment_id]
                if len(kept) != len(entries):
                    transaction.set(reference, self._record_fields(kept))

            self._in_transaction(work)

    def _login_failure(self, client_key: str, window: int):
        return self.db.collection("loginFailures").document(f"{client_key}-{window}")

    def login_failures(self, client_key: str, window: int) -> int:
        snapshot = self._login_failure(client_key, window).get()
        return int(snapshot.get("count") or 0) if snapshot.exists else 0

    def add_login_failure(self, client_key: str, window: int, expire_at: float) -> None:
        # Increment はサーバー側で足すので、同時に失敗しても数え漏れない
        self._login_failure(client_key, window).set(
            {"count": firestore.Increment(1), "expire_at": datetime.fromtimestamp(expire_at, tz=timezone.utc)}, merge=True
        )

    def save_offline_verifiers(self, class_id: str, verifiers: Doc) -> None:
        # クラスの下に置くので、クラスを消すとまとめて消える
        self._class(class_id).collection("offline").document("verifiers").set(verifiers)

    def offline_verifiers(self, class_id: str) -> Doc | None:
        snapshot = self._class(class_id).collection("offline").document("verifiers").get()
        return snapshot.to_dict() if snapshot.exists else None

    def delete_assignment(self, assignment_id: str) -> None:
        reference = self._assignment(assignment_id)
        owner: dict[str, str] = {}

        def release(transaction) -> None:
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                return
            owner["class_id"] = snapshot.get("class_id")
            class_reference = self._class(owner["class_id"])
            classroom = class_reference.get(transaction=transaction)
            if classroom.exists and classroom.get("open_assignment_id") == assignment_id:
                transaction.update(class_reference, {"open_assignment_id": None})

        # 先に受付中の印を外し、そのあと子の文書ごと消す。生徒ごとの記録からもその課題の分を外す
        self._in_transaction(release)
        self.db.recursive_delete(reference)
        self._expiry_cache.pop(assignment_id, None)
        if "class_id" in owner:
            self.remove_entries(owner["class_id"], assignment_id)

    def delete_class(self, class_id: str) -> None:
        # 授業コードを先に消して、新しい入室を止める
        codes = self.db.collection("classCodes").where(filter=FieldFilter("class_id", "==", class_id))
        for snapshot in codes.stream():
            snapshot.reference.delete()
        assignments = self.db.collection("assignments").where(filter=FieldFilter("class_id", "==", class_id))
        for snapshot in assignments.stream():
            self.db.recursive_delete(snapshot.reference)
            self._expiry_cache.pop(snapshot.id, None)
        # 個人コードの対応（credentials）と生徒ごとの記録（students）もクラスの下にあるので、まとめて消える
        self.db.recursive_delete(self._class(class_id))
