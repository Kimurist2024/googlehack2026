"""ムシトリのAPI。生徒のコードは実行せず、Geminiも直接は呼ばない。"""
import csv
import io
import logging
import os
import re
import secrets
import threading
from pathlib import Path
from typing import Annotated, Callable, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi import Path as PathParam
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from qgen.ai import QuizAI, default_ai
from qgen.sandbox import Sandbox, default_sandbox

from . import audit, auth, classpack, demo, offline_api, security, service
from .store import AssignmentRecord, ClassRecord, Store, can_add_submissions, can_begin_generation, default_store, is_expired

logger = logging.getLogger(__name__)
GRACE_SEC = 10
# 失敗した入室だけを、接続元ごと・1分ごとに数える。保存先に数えるので、インスタンスが増えても上限は変わらない。
# コードは31種類の文字の8桁が2つなので、この回数でも総当たりはできない
LOGIN_FAILURES_PER_MIN = 30
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
# multipart の区切りなどの分を足した、リクエスト本文の上限
MAX_BODY_BYTES = MAX_UPLOAD_BYTES + 256 * 1024
# サーバーが作るID（secrets.token_hex(8)）の形。これ以外は保存先に問い合わせる前に断る
ID_PATTERN = r"^[0-9a-f]{16}$"
# 授業コードが違っていたときも同じ回数だけ保存先を読み、応答時間から「どちらが違うか」を推測させない
NO_CLASS_ID = "0" * 16
MAX_STDIN_CHARS = 2_000
NUMBER_PATTERN = r"^[A-Za-z0-9_-]{1,20}$"
# explained と not_explained は、質問案で聞いた結果。生徒の記録に残り、次の課題の材料になる
ACTIONS = {"explained", "not_explained", "ask_in_class", "no_problem", "question_bad"}
EXPLANATION_CHARS = 300
QUESTION_TYPES = {"output", "trace", "impact"}
MAX_ANSWER_CHARS = 20_000
MAX_ANSWERS = 10
GENERATION_STALE_SEC = 30 * 60
# 画面のファイル。リポジトリでは apps/api/app/main.py から見て ../../web にある
WEB_DIR = Path(os.environ.get("WEB_DIR") or Path(__file__).resolve().parents[2] / "web")
# 生徒のデータ（提出コード、問い、正解、解答と採点結果、声かけの記録）を残す日数。課題を作った時点から数える
DEFAULT_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 365
# 表計算ソフトが数式として実行してしまう先頭の文字（CSV インジェクション）
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

ResourceId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
AssignmentId = Annotated[str, PathParam(pattern=ID_PATTERN)]
ClassId = Annotated[str, PathParam(pattern=ID_PATTERN)]
StudentId = Annotated[str, PathParam(pattern=ID_PATTERN)]


class ClassIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    student_numbers: list[str] = Field(min_length=1, max_length=400)

    @field_validator("student_numbers")
    @classmethod
    def numbers_are_unique(cls, numbers: list[str]) -> list[str]:
        if len(set(numbers)) != len(numbers):
            raise ValueError("番号が重複しています")
        if not all(re.fullmatch(NUMBER_PATTERN, number) for number in numbers):
            raise ValueError("番号は英数字で入力してください（氏名は入れません）")
        return numbers


class AssignmentIn(BaseModel):
    class_id: ResourceId
    title: str = Field(min_length=1, max_length=120)
    learning_goal: str = Field(default="", max_length=400)
    stdin_examples: list[Annotated[str, StringConstraints(max_length=MAX_STDIN_CHARS)]] = Field(default_factory=list, max_length=20)
    time_limit_sec: int = Field(default=300, ge=60, le=1800)
    question_count: int = Field(default=3, ge=1, le=5)
    weights: dict[str, float] = Field(default_factory=lambda: {"output": 1.0, "trace": 1.0, "impact": 1.0})

    @field_validator("weights")
    @classmethod
    def weights_in_range(cls, weights: dict[str, float]) -> dict[str, float]:
        if not set(weights) <= QUESTION_TYPES:
            raise ValueError("重みの種類が正しくありません")
        if not all(1 <= value <= 3 for value in weights.values()):
            raise ValueError("重みは1から3の間で指定してください")
        return weights


class SessionIn(BaseModel):
    class_code: str = Field(min_length=4, max_length=32)
    personal_code: str = Field(min_length=4, max_length=32)


class SubmitIn(BaseModel):
    answers: dict[Annotated[str, StringConstraints(max_length=64)], Annotated[str, StringConstraints(max_length=MAX_ANSWER_CHARS)]] = Field(
        max_length=MAX_ANSWERS
    )


class ChatTurn(BaseModel):
    role: Literal["student", "ai"]
    text: str = Field(max_length=400)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=300)
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)


class ExplainIn(BaseModel):
    line: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=EXPLANATION_CHARS)


class ActionIn(BaseModel):
    action: str
    reason: str = Field(default="", max_length=400)
    duration_ms: int = Field(default=0, ge=0, le=3_600_000)

    @model_validator(mode="after")
    def reason_when_no_problem(self) -> "ActionIn":
        if self.action not in ACTIONS:
            raise ValueError("処置の種類が正しくありません")
        if self.action == "no_problem" and not self.reason.strip():
            raise ValueError("「問題なし」には理由が必要です")
        return self


def retention_sec() -> float:
    """RETENTION_DAYS（1〜365日）。必要以上に残さないよう、既定は30日にする。"""
    try:
        days = int(os.environ.get("RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
    except ValueError:
        days = DEFAULT_RETENTION_DAYS
    return min(max(days, 1), MAX_RETENTION_DAYS) * 24 * 60 * 60


def csv_cell(value: object) -> object:
    """表計算ソフトで開いたときに数式として動かないようにする。"""
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def warm_up(shared_ai: Callable[[], QuizAI]) -> None:
    """起動の直後に裏で呼ぶ。失敗しても、最初の要求のときにもう一度準備されるだけなので止めない。"""
    for name, step in (("firebase", auth.prepare_firebase), ("ai", shared_ai)):
        try:
            step()
        except Exception:
            logger.warning("起動直後の準備に失敗しました step=%s", name, exc_info=True)


class NoCacheStaticFiles(StaticFiles):
    """手元の開発で画面を配る。本番の Firebase Hosting（firebase.json）と同じく、毎回配信元に新しい版を確かめさせる。"""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["cache-control"] = "no-cache"
        return response


def create_app(
    store: Store | None = None,
    sandbox_factory: Callable[[], Sandbox] = default_sandbox,
    ai_factory: Callable[[], QuizAI] = default_ai,
) -> FastAPI:
    local = auth.is_local()
    # API の一覧（/docs、/openapi.json）は攻撃の手がかりになるので、手元の開発のときだけ出す
    app = FastAPI(
        title="ムシトリ API",
        docs_url="/docs" if local else None,
        redoc_url=None,
        openapi_url="/openapi.json" if local else None,
    )
    # 後に足したものが外側になる。413 の応答にもヘッダーが付くよう、ヘッダーを最後に足す
    app.add_middleware(security.BodyLimit, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(security.SecurityHeaders, https_only=not local)
    store = store or default_store()
    app.state.store = store
    # Gemini と Model Armor のクライアントは、作るたびに認証と接続の準備をするので、1つを作って使い回す
    shared: list[QuizAI] = []
    shared_lock = threading.Lock()

    def shared_ai() -> QuizAI:
        with shared_lock:
            if not shared:
                shared.append(ai_factory())
            return shared[0]

    # ネットが落ちても授業を止めないための入口（授業パッケージ、校内LAN版、オフライン提出）。ここより後の経路より優先される
    offline_api.install(app, store, shared_ai, grace_sec=GRACE_SEC, login_limit=LOGIN_FAILURES_PER_MIN)
    if not local:
        # 起動の直後に、最初の要求で必要になる準備（Firebase、Gemini のクライアント）を裏で済ませておく
        threading.Thread(target=warm_up, args=(shared_ai,), daemon=True).start()

    def owned_class(class_id: str, teacher: str) -> ClassRecord:
        classroom = store.get_class(class_id)
        if classroom is None or classroom.teacher != teacher:
            raise HTTPException(status_code=404, detail="クラスが見つかりません")
        return classroom

    def owned_assignment(assignment_id: str, teacher: str) -> AssignmentRecord:
        assignment = store.get_assignment(assignment_id)
        # TTL の削除は遅れることがあるので、期限を過ぎたものはここでないものとして扱う
        if assignment is None or is_expired(assignment, service.now()):
            raise HTTPException(status_code=404, detail="課題が見つかりません")
        owned_class(assignment.class_id, teacher)
        return assignment

    def student_assignment(assignment_id: str, claims: dict) -> AssignmentRecord:
        assignment = store.get_assignment(assignment_id)
        if assignment is None or assignment.class_id != claims["class"] or is_expired(assignment, service.now()):
            raise HTTPException(status_code=404, detail="課題が見つかりません")
        return assignment

    def run_generation(assignment: AssignmentRecord) -> None:
        try:
            service.generate_all(store, assignment, sandbox_factory(), shared_ai())
        except Exception:
            # 「生成中」のまま止まらないようにして、やり直せる状態に戻す
            store.end_generation(assignment.id, "draft")
            raise

    def run_followups(assignment: AssignmentRecord) -> None:
        ai = shared_ai()
        service.create_followups(store, assignment, ai)
        service.create_class_summary(store, assignment, ai)

    # Cloud Run は末尾が z のパス（/healthz など）を予約していて、アプリまで届かない
    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/me")
    def me(teacher: str = Depends(auth.current_teacher)) -> dict:
        """ログインしたアカウントが教員として通るかを、画面が確かめるのに使う。"""
        return {"email": teacher}

    @app.post("/v1/dev/seed", status_code=201)
    def seed_demo(request: Request, teacher: str = Depends(auth.current_teacher)) -> dict:
        """合成データのデモを作る。手元の開発か、ALLOW_DEMO_SEED=1 の本番で、ログインした教員だけが使える。"""
        if not auth.demo_seed_enabled():
            raise HTTPException(status_code=404, detail="Not Found")
        created = create_class(ClassIn(name="デモクラス", student_numbers=list(demo.PROGRAMS)), request, teacher)
        assignment_id = create_assignment(
            AssignmentIn(class_id=created["class_id"], title=demo.TITLE, learning_goal=demo.LEARNING_GOAL, weights=demo.WEIGHTS),
            request,
            teacher,
        )["assignment_id"]
        by_number = {number: sid for sid, number in store.get_class(created["class_id"]).student_numbers.items()}
        store.add_submissions(assignment_id, {by_number[number]: code for number, code in demo.PROGRAMS.items()})
        expires_at = store.get_assignment(assignment_id).expire_at
        # これまでの課題の記録も合成で入れる。締切のときに、記録との違いから質問案を作る。
        # 期限はデモの課題と同じにして、デモと一緒に消えるようにする
        for number, student_id in by_number.items():
            for entry in demo.past_entries(number, service.now()):
                store.save_student_entry(created["class_id"], student_id, {**entry, "expire_at": expires_at})
        return {**created, "assignment_id": assignment_id, "expires_at": expires_at}

    @app.post("/v1/classes", status_code=201)
    def create_class(body: ClassIn, request: Request, teacher: str = Depends(auth.current_teacher)) -> dict:
        class_id = secrets.token_hex(8)
        class_code = auth.new_code()
        numbers: dict[str, str] = {}
        credentials: dict[str, str] = {}
        codes: dict[str, str] = {}
        by_student: dict[str, str] = {}
        for number in body.student_numbers:
            student_id = secrets.token_hex(8)
            code = auth.new_code()
            numbers[student_id] = number
            credentials[auth.code_hash(code)] = student_id
            codes[number] = code
            by_student[student_id] = code
        store.create_class(ClassRecord(class_id, body.name, teacher, numbers), auth.code_hash(class_code), credentials)
        # 授業パッケージ用の照合値。コードの平文があるのはこの時だけなので、ここで作る
        store.save_offline_verifiers(class_id, classpack.make_verifiers(class_code, by_student))
        audit.event("class.created", request, principal=teacher, class_id=class_id, count=len(numbers))
        # コードを平文で返すのはこの1回だけ
        return {"class_id": class_id, "class_code": class_code, "personal_codes": codes}

    @app.post("/v1/assignments", status_code=201)
    def create_assignment(body: AssignmentIn, request: Request, teacher: str = Depends(auth.current_teacher)) -> dict:
        owned_class(body.class_id, teacher)
        assignment_id = secrets.token_hex(8)
        store.create_assignment(
            AssignmentRecord(
                id=assignment_id,
                class_id=body.class_id,
                title=body.title,
                learning_goal=body.learning_goal,
                stdin_examples=body.stdin_examples,
                time_limit_sec=body.time_limit_sec,
                question_count=body.question_count,
                weights=body.weights,
                expire_at=service.now() + retention_sec(),
            )
        )
        audit.event("assignment.created", request, principal=teacher, class_id=body.class_id, assignment_id=assignment_id)
        return {"assignment_id": assignment_id}

    @app.post("/v1/assignments/{assignment_id}/submissions")
    async def upload_submissions(
        assignment_id: AssignmentId, request: Request, file: UploadFile = File(...), teacher: str = Depends(auth.current_teacher)
    ) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        locked = HTTPException(status_code=409, detail="受付を始めた課題には提出を追加できません")
        if not can_add_submissions(assignment):
            raise locked
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="ファイルが大きすぎます")
        classroom = store.get_class(assignment.class_id)
        by_number = {number: student_id for student_id, number in classroom.student_numbers.items()}
        try:
            found, problems = service.read_submissions(data, set(by_number))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        if not store.add_submissions(assignment_id, {by_number[number]: code for number, code in found.items()}):
            raise locked
        audit.event("submissions.uploaded", request, principal=teacher, assignment_id=assignment_id, count=len(found), problems=len(problems))
        return {"accepted": len(found), "problems": problems}

    @app.post("/v1/assignments/{assignment_id}:generate", status_code=202)
    def generate(assignment_id: AssignmentId, request: Request, tasks: BackgroundTasks, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        if not store.submission_counts(assignment_id):
            raise HTTPException(status_code=409, detail="提出がありません")
        if not store.begin_generation(assignment_id, service.now(), GENERATION_STALE_SEC):
            raise HTTPException(status_code=409, detail="今は問いを作れません")
        audit.event("generation.started", request, principal=teacher, assignment_id=assignment_id)
        tasks.add_task(run_generation, assignment)
        return {"state": "generating"}

    @app.get("/v1/assignments/{assignment_id}")
    def assignment_status(assignment_id: AssignmentId, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        return {
            "state": assignment.state,
            "title": assignment.title,
            "submissions": store.submission_counts(assignment_id),
            "expires_at": assignment.expire_at,
        }

    @app.delete("/v1/assignments/{assignment_id}", status_code=204)
    def delete_assignment(assignment_id: AssignmentId, request: Request, teacher: str = Depends(auth.current_teacher)) -> Response:
        """課題と、その生徒のデータをすべて消す。期限を待たずに消したいときに使う。"""
        assignment = owned_assignment(assignment_id, teacher)
        # 生成の途中で消すと、裏で動いている処理と食い違うので、終わるまで待ってもらう
        if assignment.state == "generating" and not can_begin_generation(assignment, service.now(), GENERATION_STALE_SEC):
            raise HTTPException(status_code=409, detail="問いを作っている間は消せません")
        store.delete_assignment(assignment_id)
        audit.event("assignment.deleted", request, principal=teacher, assignment_id=assignment_id)
        return Response(status_code=204)

    @app.delete("/v1/classes/{class_id}", status_code=204)
    def delete_class(class_id: ClassId, request: Request, teacher: str = Depends(auth.current_teacher)) -> Response:
        """クラス、名簿、授業コードと個人コード、クラスのすべての課題を消す。"""
        owned_class(class_id, teacher)
        store.delete_class(class_id)
        audit.event("class.deleted", request, principal=teacher, class_id=class_id)
        return Response(status_code=204)

    @app.post("/v1/assignments/{assignment_id}:open")
    def open_assignment(assignment_id: AssignmentId, request: Request, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        if assignment.state != "ready":
            raise HTTPException(status_code=409, detail="問いの生成が終わっていません")
        if not store.open_assignment(assignment_id):
            raise HTTPException(status_code=409, detail="受付中の課題がすでにあります")
        audit.event("assignment.opened", request, principal=teacher, assignment_id=assignment_id)
        return {"state": "open"}

    @app.post("/v1/assignments/{assignment_id}:close")
    def close_assignment(assignment_id: AssignmentId, request: Request, tasks: BackgroundTasks, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        if not store.close_assignment(assignment_id):
            raise HTTPException(status_code=409, detail="受付中ではありません")
        audit.event("assignment.closed", request, principal=teacher, assignment_id=assignment_id)
        tasks.add_task(run_followups, assignment)
        return {"state": "closed"}

    @app.post("/v1/sessions")
    def create_session(body: SessionIn, request: Request) -> dict:
        client = security.client_key(request)
        current = service.now()
        window = int(current // 60)
        if store.login_failures(client, window) >= LOGIN_FAILURES_PER_MIN:
            audit.event("login.rate_limited", request, severity="WARNING", client=client, forwarded=security.forwarded_count(request))
            raise HTTPException(
                status_code=429, detail="しばらく待ってからやり直してください", headers={"Retry-After": str(60 - int(current % 60))}
            )
        class_id = store.class_id_for_code(auth.code_hash(body.class_code))
        classroom = store.get_class(class_id) if class_id else None
        student_id = store.student_for_credential(classroom.id if classroom else NO_CLASS_ID, auth.code_hash(body.personal_code))
        if classroom is None or student_id is None:
            # 教室の全員が同じ接続元から入っても、正しいコードの入室では上限に近づかない
            store.add_login_failure(client, window, expire_at=(window + 2) * 60)
            audit.event("login.failed", request, severity="WARNING", client=client, forwarded=security.forwarded_count(request))
            raise HTTPException(status_code=401, detail="コードが正しくありません")
        audit.event(
            "login.succeeded", request, class_id=classroom.id, student_id=student_id, client=client, forwarded=security.forwarded_count(request)
        )
        return {
            "token": auth.issue_student_token(classroom.id, student_id),
            "assignment_id": classroom.open_assignment_id,
            "number": classroom.student_numbers[student_id],
        }

    @app.post("/v1/assignments/{assignment_id}/attempt:start")
    def start_attempt(assignment_id: AssignmentId, claims: dict = Depends(auth.current_student)) -> dict:
        assignment = student_assignment(assignment_id, claims)
        student_id = claims["student"]
        if assignment.state != "open":
            raise HTTPException(status_code=409, detail="受付中ではありません")
        quiz = store.get_quiz(assignment_id, student_id)
        if quiz is None:
            raise HTTPException(status_code=409, detail="この提出には問いがありません。先生に確認してください")
        attempt = store.start_attempt(assignment_id, student_id, service.now())
        if attempt["submitted_at"] is not None:
            raise HTTPException(status_code=409, detail="すでに提出済みです")
        deadline = attempt["started_at"] + assignment.time_limit_sec
        return {"questions": quiz["questions"], "code": quiz["code"], "stdin": quiz["stdin"], "remaining_sec": max(0, round(deadline - service.now()))}

    @app.post("/v1/assignments/{assignment_id}/attempt:submit")
    def submit_attempt(assignment_id: AssignmentId, body: SubmitIn, claims: dict = Depends(auth.current_student)) -> dict:
        assignment = student_assignment(assignment_id, claims)
        student_id = claims["student"]
        attempt = store.get_attempt(assignment_id, student_id)
        already_submitted = HTTPException(status_code=409, detail="すでに提出済みです")
        if attempt is None:
            raise HTTPException(status_code=409, detail="まだ開始していません")
        if attempt["submitted_at"] is not None:
            raise already_submitted
        if assignment.state != "open":
            raise HTTPException(status_code=409, detail="受付は終了しました")
        if service.now() > attempt["started_at"] + assignment.time_limit_sec + GRACE_SEC:
            raise HTTPException(status_code=410, detail="持ち時間を過ぎました")
        key = store.get_answer_key(assignment_id, student_id)
        graded = service.grade(key, body.answers)
        if not store.finish_attempt(assignment_id, student_id, graded, service.now()):
            raise already_submitted
        return {
            "score": sum(1 for item in graded if item["correct"]),
            "total": len(graded),
            "results": graded,
            "trace": key["trace"],
            "notice": "この結果は成績には使いません。",
        }

    @app.post("/v1/assignments/{assignment_id}/attempt:chat")
    def chat(assignment_id: AssignmentId, body: ChatIn, claims: dict = Depends(auth.current_student)) -> dict:
        """解答を送ったあとの振り返り。AI は答えを言わず、ヒントか問い返しを返す。"""
        student_assignment(assignment_id, claims)
        student_id = claims["student"]
        attempt = store.get_attempt(assignment_id, student_id)
        if attempt is None or attempt["submitted_at"] is None:
            raise HTTPException(status_code=409, detail="解答を送ったあとに使えます")
        remaining = store.use_chat_turn(assignment_id, student_id, service.CHAT_LIMIT)
        if remaining is None:
            raise HTTPException(status_code=429, detail="この課題で質問できる回数を使い切りました")
        context = service.chat_context(store, assignment_id, student_id, attempt)
        reply = shared_ai().chat(context, [turn.model_dump() for turn in body.history], body.message)
        return {**reply, "remaining": remaining}

    @app.post("/v1/assignments/{assignment_id}/attempt:explain")
    def explain(assignment_id: AssignmentId, body: ExplainIn, claims: dict = Depends(auth.current_student)) -> dict:
        """説明できなかった行を、生徒が自分の言葉で書く。AIは使わず、そのまま教員に見せる。"""
        student_assignment(assignment_id, claims)
        student_id = claims["student"]
        attempt = store.get_attempt(assignment_id, student_id)
        if attempt is None or attempt["submitted_at"] is None:
            raise HTTPException(status_code=409, detail="解答を送ったあとに使えます")
        if body.line not in service.explainable_lines(attempt, store.get_answer_key(assignment_id, student_id)):
            raise HTTPException(status_code=400, detail="この行は説明の対象ではありません")
        if not store.save_explanation(assignment_id, student_id, body.line, body.text.strip()):
            raise HTTPException(status_code=409, detail="解答を送ったあとに使えます")
        return {"saved": True}

    @app.get("/v1/assignments/{assignment_id}/followups")
    def followups(
        assignment_id: AssignmentId, budget_sec: Annotated[float, Query(ge=0, le=3600)] = 90, teacher: str = Depends(auth.current_teacher)
    ) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        return service.followup_view(store, assignment, store.get_class(assignment.class_id), budget_sec)

    @app.post("/v1/assignments/{assignment_id}/followups/{student_id}")
    def record_action(
        assignment_id: AssignmentId, student_id: StudentId, body: ActionIn, request: Request, teacher: str = Depends(auth.current_teacher)
    ) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        if student_id not in store.get_class(assignment.class_id).student_numbers:
            raise HTTPException(status_code=404, detail="生徒が見つかりません")
        store.record_action(
            assignment_id, student_id, {"action": body.action, "reason": body.reason, "duration_ms": body.duration_ms, "by": teacher}
        )
        store.set_entry_action(assignment.class_id, student_id, assignment_id, {"action": body.action, "reason": body.reason})
        audit.event("followup.recorded", request, principal=teacher, assignment_id=assignment_id, student_id=student_id, action=body.action)
        return {"saved": True}

    @app.get("/v1/assignments/{assignment_id}/students/{student_id}/record")
    def student_record(
        assignment_id: AssignmentId, student_id: StudentId, request: Request, teacher: str = Depends(auth.current_teacher)
    ) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        classroom = store.get_class(assignment.class_id)
        if student_id not in classroom.student_numbers:
            raise HTTPException(status_code=404, detail="生徒が見つかりません")
        # 課題をまたいだ記録をまとめて見る操作なので、誰がどの生徒の記録を見たかを残す
        audit.event("student_record.viewed", request, principal=teacher, class_id=classroom.id, student_id=student_id)
        return service.student_record_view(store, classroom, student_id)

    @app.get("/v1/assignments/{assignment_id}/export")
    def export(assignment_id: AssignmentId, request: Request, teacher: str = Depends(auth.current_teacher)) -> Response:
        assignment = owned_assignment(assignment_id, teacher)
        classroom = store.get_class(assignment.class_id)
        submissions = store.submission_statuses(assignment_id)
        attempts = store.attempts(assignment_id)
        followups = store.followups(assignment_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["number", "status", "reason", "score", "total", "action", "duration_ms"])
        for student_id, number in classroom.student_numbers.items():
            submission = submissions.get(student_id, {})
            attempt = attempts.get(student_id, {})
            graded = attempt.get("graded", [])
            record = followups.get(student_id, {})
            row = [
                number,
                submission.get("status", "not_submitted"),
                submission.get("reason") or "",
                sum(1 for item in graded if item["correct"]) if graded else "",
                len(graded) if graded else "",
                record.get("action", ""),
                record.get("duration_ms", ""),
            ]
            writer.writerow([csv_cell(value) for value in row])
        # 成績に近い情報がまとめて出ていくので、誰がいつ持ち出したかを必ず残す
        audit.event("export.downloaded", request, principal=teacher, assignment_id=assignment_id, count=len(classroom.student_numbers))
        return Response(
            content=output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="mushitori-{assignment_id}.csv"'},
        )

    if os.environ.get("SERVE_WEB") == "1":
        # 手元の開発だけで使う。本番の画面は Firebase Hosting が apps/web から配る
        app.mount("/", NoCacheStaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
