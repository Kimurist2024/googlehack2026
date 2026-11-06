"""ネットが落ちても授業を止めないための API。準備はクラウド、授業はどこでも。

  ① ふだん      ：クラウドで授業。教員は授業前に「授業パッケージ」を教員PCに保存しておく
  ② ネット障害  ：教員PCが DEPLOY_MODE=lan でパッケージを取り込み、校内LANで授業を引き継ぐ。
                   終わったら結果を書き出し、クラウドに取り込む（クラウドが採点し直す）
  ③ LANも障害   ：生徒の端末が解答をためておき、つながったら attempt:submit-offline で送る

main.py の経路はそのまま使い、ここでは足りない入口だけを足す。create_app の最初で install を呼ぶ。
LAN版の入室（/v1/sessions）はここで先に登録するので、main.py の同じ経路より優先される。
"""
import os
import re
import secrets
from typing import Callable, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.middleware import Middleware

from . import audit, auth, classpack, security, service
from .access import student_assignment
from .fields import (
    CLOCK_SKEW_SEC,
    GENERATION_STALE_SEC,
    MAX_ANSWERS,
    MAX_DURATION_MS,
    REASON_CHARS,
    AnswerKey,
    AnswerText,
    AssignmentId,
    ResourceId,
)
from .store import AssignmentRecord, ClassRecord, Store, is_expired

# 解答を端末にためておける長さ。これを過ぎた提出は受け付けない
OFFLINE_WINDOW_SEC = 24 * 60 * 60
LAN_TEACHER = "lan-teacher"
LOOPBACK = {"127.0.0.1", "::1"}
# 校内LAN版でも、教室の端末から誰でも呼べる経路。これ以外は教員PC（ループバック）からだけ受け付ける
LAN_STUDENT_PATHS = [
    ("GET", re.compile(r"^/(?!v1/).*$")),
    ("HEAD", re.compile(r"^/(?!v1/).*$")),
    ("GET", re.compile(r"^/v1/health$")),
    ("POST", re.compile(r"^/v1/sessions$")),
    ("POST", re.compile(r"^/v1/assignments/[0-9a-f]{16}/attempt:(start|submit|submit-offline)$")),
]
# 校内LAN版では使わない経路。問いを作るにはコードの実行と AI が要るので、クラウドでだけ行う
LAN_DISABLED_PATHS = [
    ("POST", re.compile(r"^/v1/classes$")),
    ("POST", re.compile(r"^/v1/assignments$")),
    ("POST", re.compile(r"^/v1/assignments/[^/]+/submissions$")),
    ("POST", re.compile(r"^/v1/assignments/[^/]+:generate$")),
    ("POST", re.compile(r"^/v1/assignments/[^/]+/(package|edge-results)$")),
    ("POST", re.compile(r"^/v1/dev/seed$")),
]
# 校内LAN版で設定されていたら起動しない。外とつながる設定が残っていると、オフラインの約束が守れない
CLOUD_SETTINGS = {
    "STORE_BACKEND": {"firestore"},
    "AI_BACKEND": {"gemini"},
    "SANDBOX_BACKEND": {"code_execution"},
}
CLOUD_ONLY_SETTINGS = ("MODEL_ARMOR_TEMPLATE", "PACKAGE_SIGNING_KMS_KEY", "PACKAGE_SIGNING_KEY")


def is_lan() -> bool:
    return os.environ.get("DEPLOY_MODE") == "lan"


def check_lan_settings() -> None:
    problems = [name for name, values in CLOUD_SETTINGS.items() if os.environ.get(name) in values]
    problems += [name for name in CLOUD_ONLY_SETTINGS if os.environ.get(name)]
    if problems:
        raise RuntimeError(f"校内LAN版では次の設定を外してください: {', '.join(problems)}")


def is_loopback(request: Request) -> bool:
    return bool(request.client) and request.client.host in LOOPBACK


class LanGuard:
    """校内LAN版の入口を絞る ASGI ミドルウェア。教員の操作は教員PCからだけにする。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        if any(method == m and pattern.match(path) for m, pattern in LAN_DISABLED_PATHS):
            return await security.reject(send, 404, "校内LAN版では使えません。クラウドで行ってください")
        student = any(method == m and pattern.match(path) for m, pattern in LAN_STUDENT_PATHS)
        client = (scope.get("client") or ("", 0))[0]
        if not student and client not in LOOPBACK:
            return await security.reject(send, 403, "この操作は教員のPCからだけ行えます")
        await self.app(scope, receive, send)


def lan_teacher(request: Request) -> str:
    """校内LAN版の教員。ミドルウェアに加えて、ここでも教員PCからの接続かを確かめる。"""
    if not is_loopback(request):
        raise HTTPException(status_code=403, detail="この操作は教員のPCからだけ行えます")
    return LAN_TEACHER


def lan_public_key() -> str | None:
    pem = os.environ.get("PACKAGE_PUBLIC_KEY", "").strip()
    path = os.environ.get("PACKAGE_PUBLIC_KEY_FILE", "").strip()
    if not pem and path and os.path.exists(path):
        with open(path, encoding="ascii") as handle:
            pem = handle.read().strip()
    return pem or None


def lan_urls() -> list[str]:
    """生徒に案内するURL。起動スクリプト（scripts/lan.py）が決めた値を使う。

    ここで名前解決をすると DNS への問い合わせ（外への通信）になりうるので、自分では調べない。
    """
    explicit = os.environ.get("LAN_PUBLIC_URL", "").strip()
    return [explicit] if explicit else []


class SessionIn(BaseModel):
    class_code: str = Field(min_length=1, max_length=32)
    personal_code: str = Field(min_length=1, max_length=32)


class OfflineSubmitIn(BaseModel):
    answers: dict[AnswerKey, AnswerText] = Field(max_length=MAX_ANSWERS)
    answered_at: float = Field(ge=0)


class ImportIn(BaseModel):
    sealed: str = Field(min_length=1, max_length=12_000_000)
    unlock_code: str = Field(min_length=1, max_length=64)


class EdgeAttempt(BaseModel):
    started_at: float = Field(ge=0)
    submitted_at: float | None = Field(default=None, ge=0)
    answers: dict[AnswerKey, AnswerText] = Field(default_factory=dict, max_length=MAX_ANSWERS)


class EdgeFollowup(BaseModel):
    action: Literal["ask_in_class", "no_problem", "question_bad"]
    reason: str = Field(default="", max_length=REASON_CHARS)
    duration_ms: int = Field(default=0, ge=0, le=MAX_DURATION_MS)


class EdgeResults(BaseModel):
    format: Literal["mushitori-results-v1"]
    assignment_id: ResourceId
    attempts: dict[ResourceId, EdgeAttempt] = Field(default_factory=dict, max_length=1000)
    followups: dict[ResourceId, EdgeFollowup] = Field(default_factory=dict, max_length=1000)


def install(app: FastAPI, store: Store, shared_ai: Callable, grace_sec: float, login_limit: int) -> None:
    router = APIRouter()

    def owned_assignment(assignment_id: str, teacher: str) -> tuple[AssignmentRecord, ClassRecord]:
        """課題とクラスを読み、担当教員と保存期限を確かめる。"""
        assignment = store.get_assignment(assignment_id)
        classroom = store.get_class(assignment.class_id) if assignment else None
        if assignment is None or classroom is None or classroom.teacher != teacher or is_expired(assignment, service.now()):
            raise HTTPException(status_code=404, detail="課題が見つかりません")
        return assignment, classroom

    def student_result(assignment_id: str, student_id: str, graded: list[dict], offline: bool, already: bool = False) -> dict:
        key = store.get_answer_key(assignment_id, student_id)
        return {
            **service.result_view(graded, key),
            "offline": offline,
            "already_submitted": already,
        }

    def stored_result(assignment_id: str, student_id: str) -> dict:
        """送り直しへの応答。返事だけが途中で失われた場合、解答はもう届いているので、その結果を返す。"""
        attempt = store.get_attempt(assignment_id, student_id)
        return student_result(assignment_id, student_id, attempt["graded"], attempt.get("via") == "offline", already=True)

    # --- ③ 生徒の端末にためておいた解答 ---

    @router.post("/v1/assignments/{assignment_id}/attempt:submit-offline")
    def submit_offline(
        assignment_id: AssignmentId, body: OfflineSubmitIn, request: Request, tasks: BackgroundTasks, authorization: str = Header(default="")
    ) -> dict:
        """通信が戻ってから届いた解答を受け付ける。持ち時間を過ぎていたら、オフラインの印を付けて先生に見せる。"""
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="認証が必要です")
        # ためている間に入室の期限が切れても、署名が正しく、期限から OFFLINE_WINDOW_SEC 以内なら受け付ける
        claims = auth.read_student_token(authorization[len("Bearer "):], leeway_sec=OFFLINE_WINDOW_SEC)
        student_id = claims["student"]
        assignment = student_assignment(store, assignment_id, claims)
        attempt = store.get_attempt(assignment_id, student_id)
        if attempt is None:
            raise HTTPException(status_code=409, detail="まだ開始していません")
        if attempt["submitted_at"] is not None:
            # 端末は何度でも送り直すので、同じ結果を返す（冪等）。最初に届いた解答が正になる
            return stored_result(assignment_id, student_id)
        if assignment.state not in ("open", "closed"):
            raise HTTPException(status_code=409, detail="受付中ではありません")
        now = service.now()
        if now > attempt["started_at"] + OFFLINE_WINDOW_SEC:
            raise HTTPException(status_code=410, detail="時間が経ちすぎたため受け付けられません")
        on_time = assignment.state == "open" and now <= attempt["started_at"] + assignment.time_limit_sec + grace_sec
        # 端末の時計は信用しない。記録はするが、受け付けた時刻はサーバーの時刻
        extra = {} if on_time else {"via": "offline", "answered_at_client": min(body.answered_at, now)}
        graded = service.grade(store.get_answer_key(assignment_id, student_id), body.answers)
        if not store.finish_attempt(assignment_id, student_id, graded, now, extra=extra):
            return stored_result(assignment_id, student_id)
        if not on_time:
            audit.event("attempt.offline_submitted", request, assignment_id=assignment_id, student_id=student_id)
        if assignment.state == "closed":
            # 締切のあとに届いた解答にも、授業で聞く一問を作る
            tasks.add_task(service.create_followups, store, assignment, shared_ai())
        return student_result(assignment_id, student_id, graded, offline=not on_time)

    # --- ① クラウド：授業パッケージを作る、LANの結果を取り込む ---

    @router.get("/v1/package-key")
    def package_key() -> dict:
        """教員PCが署名を確かめるための公開鍵。公開してよい。"""
        if is_lan():
            raise HTTPException(status_code=404, detail="Not Found")
        signer = classpack.default_signer()
        if signer is None:
            raise HTTPException(status_code=503, detail="署名の鍵が設定されていません")
        return {"key_id": signer.key_id, "public_key_pem": signer.public_key_pem()}

    @router.post("/v1/assignments/{assignment_id}/package")
    def make_package(assignment_id: AssignmentId, request: Request, teacher: str = Depends(auth.current_teacher)) -> dict:
        """授業パッケージを作る。解除コードはこの応答で1回だけ返し、どこにも保存しない。"""
        assignment, classroom = owned_assignment(assignment_id, teacher)
        if assignment.state not in ("ready", "open"):
            raise HTTPException(status_code=409, detail="問いを作り終えてから保存してください")
        signer = classpack.default_signer()
        if signer is None:
            raise HTTPException(status_code=503, detail="署名の鍵が設定されていないため、授業パッケージを作れません")
        try:
            payload = classpack.build_payload(store, assignment, service.now())
        except classpack.PackageError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        sealed, unlock_code = classpack.seal(payload, signer)
        # 答えを含むファイルが持ち出されるので、誰がいつ持ち出したかを必ず残す
        audit.event("package.issued", request, principal=teacher, assignment_id=assignment_id, count=len(payload["quizzes"]))
        return {
            "filename": f"mushitori-{assignment_id}.pack",
            "sealed": sealed,
            "unlock_code": unlock_code,
            "not_after": payload["not_after"],
        }

    @router.post("/v1/assignments/{assignment_id}/edge-results")
    def import_edge_results(
        assignment_id: AssignmentId, body: EdgeResults, request: Request, tasks: BackgroundTasks, teacher: str = Depends(auth.current_teacher)
    ) -> dict:
        """校内LANで行った授業の結果を取り込む。LAN 側の採点は使わず、クラウドの正解で採点し直す。"""
        assignment, classroom = owned_assignment(assignment_id, teacher)
        if body.assignment_id != assignment_id:
            raise HTTPException(status_code=400, detail="別の課題の結果です")
        now = service.now()
        imported = skipped = 0
        for student_id, item in body.attempts.items():
            key = store.get_answer_key(assignment_id, student_id)
            valid_time = item.submitted_at is not None and item.started_at <= item.submitted_at <= now + CLOCK_SKEW_SEC
            if student_id not in classroom.student_numbers or key is None or not valid_time:
                skipped += 1
                continue
            existing = store.get_attempt(assignment_id, student_id)
            if existing is not None and existing["submitted_at"] is not None:
                # クラウドですでに提出していれば、そちらを正とする
                skipped += 1
                continue
            store.start_attempt(assignment_id, student_id, item.started_at)
            graded = service.grade(key, item.answers)
            if store.finish_attempt(assignment_id, student_id, graded, item.submitted_at, extra={"via": "lan"}):
                imported += 1
            else:
                skipped += 1
        for student_id, followup in body.followups.items():
            if student_id in classroom.student_numbers:
                store.record_action(assignment_id, student_id, {**followup.model_dump(), "by": teacher, "via": "lan"})
        audit.event("edge.results_imported", request, principal=teacher, assignment_id=assignment_id, count=imported, problems=skipped)
        if assignment.state == "closed":
            tasks.add_task(service.create_followups, store, assignment, shared_ai())
        return {"imported": imported, "skipped": skipped}

    @router.get("/v1/edge/status")
    def edge_status(request: Request) -> dict:
        """画面がどのモードで動いているかを知るのに使う。"""
        if not is_lan():
            return {"mode": "internet"}
        lan_teacher(request)
        assignments = []
        for class_id in store.lan_classes():
            classroom = store.get_class(class_id)
            if classroom and classroom.open_assignment_id:
                assignment = store.get_assignment(classroom.open_assignment_id)
                if assignment:
                    assignments.append({"assignment_id": assignment.id, "title": assignment.title, "class": classroom.name, "state": assignment.state})
        return {"mode": "lan", "student_urls": lan_urls(), "assignments": assignments, "key_configured": lan_public_key() is not None}

    # --- ② 校内LAN版：教員PCで引き継ぐ ---

    if is_lan():
        check_lan_settings()
        if not hasattr(store, "lan_classes"):
            raise RuntimeError("校内LAN版は LanStore で動かしてください")
        # 一番内側に置き、断るときの応答にもセキュリティヘッダーが付くようにする
        app.user_middleware.append(Middleware(LanGuard))
        app.dependency_overrides[auth.current_teacher] = lan_teacher

        @router.post("/v1/sessions")
        def lan_session(body: SessionIn, request: Request) -> dict:
            """照合値（scrypt）で入室を確かめる。クラウドの鍵は教員PCにない。"""
            client = security.client_key(request)
            current = service.now()
            window = int(current // 60)
            if store.login_failures(client, window) >= login_limit:
                raise HTTPException(status_code=429, detail="しばらく待ってからやり直してください", headers={"Retry-After": "60"})
            classroom = verifiers = None
            for class_id in store.lan_classes():
                candidate = store.offline_verifiers(class_id)
                if candidate and classpack.match_class_code(candidate, body.class_code):
                    classroom, verifiers = store.get_class(class_id), candidate
            student_id = classpack.match_student(verifiers, body.personal_code) if verifiers else None
            if classroom is None or student_id is None:
                store.add_login_failure(client, window, expire_at=(window + 2) * 60)
                audit.event("login.failed", request, severity="WARNING", client=client)
                raise HTTPException(status_code=401, detail="コードが正しくありません")
            audit.event("login.succeeded", request, class_id=classroom.id, student_id=student_id, client=client)
            return {
                "token": auth.issue_student_token(classroom.id, student_id),
                "assignment_id": classroom.open_assignment_id,
                "number": classroom.student_numbers[student_id],
            }

        @router.post("/v1/edge/import", status_code=201)
        def import_package(body: ImportIn, request: Request, teacher: str = Depends(lan_teacher)) -> dict:
            """授業パッケージを確かめて取り込み、すぐに受付を始める。"""
            public_key = lan_public_key()
            if public_key is None:
                raise HTTPException(status_code=503, detail="クラウドの公開鍵（PACKAGE_PUBLIC_KEY）が設定されていません")
            try:
                payload = classpack.open_sealed(body.sealed, body.unlock_code, public_key, now=service.now())
            except classpack.PackageError as error:
                audit.event("package.rejected", request, severity="WARNING", reason=str(error)[:80])
                raise HTTPException(status_code=400, detail=str(error)) from None
            meta, roster = payload["assignment"], payload["class"]
            if store.get_assignment(meta["id"]) is not None:
                raise HTTPException(status_code=409, detail="この課題はすでに取り込んであります")
            if store.get_class(roster["id"]) is None:
                # 入室は照合値で確かめるので、クラウドのコードのハッシュは使わない
                store.create_class(ClassRecord(roster["id"], roster["name"], teacher, roster["student_numbers"]), secrets.token_hex(32), {})
            store.save_offline_verifiers(roster["id"], payload["verifiers"])
            expire_at = min(meta["expire_at"] or payload["not_after"], payload["not_after"])
            store.create_assignment(
                AssignmentRecord(
                    id=meta["id"],
                    class_id=roster["id"],
                    title=meta["title"],
                    learning_goal="",
                    stdin_examples=[],
                    time_limit_sec=meta["time_limit_sec"],
                    question_count=meta["question_count"],
                    weights=meta["weights"],
                    expire_at=expire_at,
                )
            )
            statuses, quizzes, keys = payload["statuses"], payload["quizzes"], payload["answer_keys"]
            store.add_submissions(meta["id"], {sid: quizzes[sid]["code"] if sid in quizzes else "" for sid in statuses})
            store.begin_generation(meta["id"], service.now(), GENERATION_STALE_SEC)
            for sid, status in statuses.items():
                if sid in quizzes and sid in keys:
                    store.save_generation_result(meta["id"], sid, "ready", None, quizzes[sid], keys[sid])
                else:
                    store.save_generation_result(meta["id"], sid, status.get("status") or "excluded", status.get("reason"), None, None)
            store.end_generation(meta["id"], "ready")
            classroom = store.get_class(roster["id"])
            if classroom.open_assignment_id:
                store.close_assignment(classroom.open_assignment_id)
            store.open_assignment(meta["id"])
            audit.event("package.imported", request, principal=teacher, assignment_id=meta["id"], count=len(quizzes))
            return {"assignment_id": meta["id"], "title": meta["title"], "student_urls": lan_urls()}

        @router.get("/v1/edge/results/{assignment_id}")
        def export_results(assignment_id: AssignmentId, request: Request, teacher: str = Depends(lan_teacher)) -> dict:
            """クラウドに取り込むための結果。答えそのものではなく、生徒が書いた解答と時刻だけを出す。"""
            assignment = store.get_assignment(assignment_id)
            if assignment is None:
                raise HTTPException(status_code=404, detail="課題が見つかりません")
            attempts = {
                sid: {
                    "started_at": attempt["started_at"],
                    "submitted_at": attempt["submitted_at"],
                    "answers": {item["id"]: item["given"] for item in attempt.get("graded", [])},
                }
                for sid, attempt in store.attempts(assignment_id).items()
            }
            followups = {
                sid: {name: record[name] for name in ("action", "reason", "duration_ms") if name in record}
                for sid, record in store.followups(assignment_id).items()
                if "action" in record
            }
            audit.event("edge.results_exported", request, principal=teacher, assignment_id=assignment_id, count=len(attempts))
            return {"format": "mushitori-results-v1", "assignment_id": assignment_id, "attempts": attempts, "followups": followups}

    app.include_router(router)
