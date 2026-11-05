"""ムシトリのAPI。生徒のコードは実行せず、Geminiも直接は呼ばない。"""
import csv
import io
import os
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated, Callable

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from qgen.ai import QuizAI, default_ai
from qgen.sandbox import Sandbox, default_sandbox

from . import auth, demo, service
from .store import AssignmentRecord, ClassRecord, Store, can_add_submissions, default_store

GRACE_SEC = 10
LOGIN_LIMIT_PER_MIN = 10
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
NUMBER_PATTERN = r"^[A-Za-z0-9_-]{1,20}$"
ACTIONS = {"ask_in_class", "no_problem", "question_bad"}
QUESTION_TYPES = {"output", "trace", "impact"}
MAX_ANSWER_CHARS = 20_000
GENERATION_STALE_SEC = 30 * 60


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
    class_id: str
    title: str = Field(min_length=1, max_length=120)
    learning_goal: str = Field(default="", max_length=400)
    stdin_examples: list[str] = Field(default_factory=list, max_length=20)
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
    answers: dict[str, Annotated[str, StringConstraints(max_length=MAX_ANSWER_CHARS)]]


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


def create_app(
    store: Store | None = None,
    sandbox_factory: Callable[[], Sandbox] = default_sandbox,
    ai_factory: Callable[[], QuizAI] = default_ai,
) -> FastAPI:
    app = FastAPI(title="ムシトリ API")
    store = store or default_store()
    app.state.store = store
    attempts_by_client: dict[str, deque] = defaultdict(deque)

    def owned_class(class_id: str, teacher: str) -> ClassRecord:
        classroom = store.get_class(class_id)
        if classroom is None or classroom.teacher != teacher:
            raise HTTPException(status_code=404, detail="クラスが見つかりません")
        return classroom

    def owned_assignment(assignment_id: str, teacher: str) -> AssignmentRecord:
        assignment = store.get_assignment(assignment_id)
        if assignment is None:
            raise HTTPException(status_code=404, detail="課題が見つかりません")
        owned_class(assignment.class_id, teacher)
        return assignment

    def student_assignment(assignment_id: str, claims: dict) -> AssignmentRecord:
        assignment = store.get_assignment(assignment_id)
        if assignment is None or assignment.class_id != claims["class"]:
            raise HTTPException(status_code=404, detail="課題が見つかりません")
        return assignment

    def run_generation(assignment: AssignmentRecord) -> None:
        try:
            service.generate_all(store, assignment, sandbox_factory(), ai_factory())
        except Exception:
            # 「生成中」のまま止まらないようにして、やり直せる状態に戻す
            store.end_generation(assignment.id, "draft")
            raise

    def run_followups(assignment: AssignmentRecord) -> None:
        service.create_followups(store, assignment, ai_factory())

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/v1/dev/seed", status_code=201)
    def seed_demo(teacher: str = Depends(auth.current_teacher)) -> dict:
        """合成データのデモを作る。ローカル開発のときだけ使える。"""
        if not auth.is_local():
            raise HTTPException(status_code=404, detail="Not Found")
        created = create_class(ClassIn(name="デモクラス", student_numbers=list(demo.PROGRAMS)), teacher)
        assignment_id = create_assignment(
            AssignmentIn(class_id=created["class_id"], title=demo.TITLE, learning_goal=demo.LEARNING_GOAL, weights=demo.WEIGHTS),
            teacher,
        )["assignment_id"]
        by_number = {number: sid for sid, number in store.get_class(created["class_id"]).student_numbers.items()}
        store.add_submissions(assignment_id, {by_number[number]: code for number, code in demo.PROGRAMS.items()})
        return {**created, "assignment_id": assignment_id}

    @app.post("/v1/classes", status_code=201)
    def create_class(body: ClassIn, teacher: str = Depends(auth.current_teacher)) -> dict:
        class_id = secrets.token_hex(8)
        class_code = auth.new_code()
        numbers: dict[str, str] = {}
        credentials: dict[str, str] = {}
        codes: dict[str, str] = {}
        for number in body.student_numbers:
            student_id = secrets.token_hex(8)
            code = auth.new_code()
            numbers[student_id] = number
            credentials[auth.code_hash(code)] = student_id
            codes[number] = code
        store.create_class(ClassRecord(class_id, body.name, teacher, numbers), auth.code_hash(class_code), credentials)
        # コードを平文で返すのはこの1回だけ
        return {"class_id": class_id, "class_code": class_code, "personal_codes": codes}

    @app.post("/v1/assignments", status_code=201)
    def create_assignment(body: AssignmentIn, teacher: str = Depends(auth.current_teacher)) -> dict:
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
            )
        )
        return {"assignment_id": assignment_id}

    @app.post("/v1/assignments/{assignment_id}/submissions")
    async def upload_submissions(assignment_id: str, file: UploadFile = File(...), teacher: str = Depends(auth.current_teacher)) -> dict:
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
        return {"accepted": len(found), "problems": problems}

    @app.post("/v1/assignments/{assignment_id}:generate", status_code=202)
    def generate(assignment_id: str, tasks: BackgroundTasks, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        if not store.submission_counts(assignment_id):
            raise HTTPException(status_code=409, detail="提出がありません")
        if not store.begin_generation(assignment_id, service.now(), GENERATION_STALE_SEC):
            raise HTTPException(status_code=409, detail="今は問いを作れません")
        tasks.add_task(run_generation, assignment)
        return {"state": "generating"}

    @app.get("/v1/assignments/{assignment_id}")
    def assignment_status(assignment_id: str, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        return {"state": assignment.state, "title": assignment.title, "submissions": store.submission_counts(assignment_id)}

    @app.post("/v1/assignments/{assignment_id}:open")
    def open_assignment(assignment_id: str, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        if assignment.state != "ready":
            raise HTTPException(status_code=409, detail="問いの生成が終わっていません")
        if not store.open_assignment(assignment_id):
            raise HTTPException(status_code=409, detail="受付中の課題がすでにあります")
        return {"state": "open"}

    @app.post("/v1/assignments/{assignment_id}:close")
    def close_assignment(assignment_id: str, tasks: BackgroundTasks, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        if not store.close_assignment(assignment_id):
            raise HTTPException(status_code=409, detail="受付中ではありません")
        tasks.add_task(run_followups, assignment)
        return {"state": "closed"}

    @app.post("/v1/sessions")
    def create_session(body: SessionIn, request: Request) -> dict:
        client = request.client.host if request.client else "unknown"
        window = attempts_by_client[client]
        current = time.monotonic()
        while window and current - window[0] > 60:
            window.popleft()
        if len(window) >= LOGIN_LIMIT_PER_MIN:
            raise HTTPException(status_code=429, detail="しばらく待ってからやり直してください")
        window.append(current)
        class_id = store.class_id_for_code(auth.code_hash(body.class_code))
        classroom = store.get_class(class_id) if class_id else None
        student_id = store.student_for_credential(class_id, auth.code_hash(body.personal_code)) if classroom else None
        if classroom is None or student_id is None:
            raise HTTPException(status_code=401, detail="コードが正しくありません")
        return {
            "token": auth.issue_student_token(classroom.id, student_id),
            "assignment_id": classroom.open_assignment_id,
            "number": classroom.student_numbers[student_id],
        }

    @app.post("/v1/assignments/{assignment_id}/attempt:start")
    def start_attempt(assignment_id: str, claims: dict = Depends(auth.current_student)) -> dict:
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
    def submit_attempt(assignment_id: str, body: SubmitIn, claims: dict = Depends(auth.current_student)) -> dict:
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

    @app.get("/v1/assignments/{assignment_id}/followups")
    def followups(assignment_id: str, budget_sec: float = 90, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        return service.followup_view(store, assignment, store.get_class(assignment.class_id), budget_sec)

    @app.post("/v1/assignments/{assignment_id}/followups/{student_id}")
    def record_action(assignment_id: str, student_id: str, body: ActionIn, teacher: str = Depends(auth.current_teacher)) -> dict:
        assignment = owned_assignment(assignment_id, teacher)
        if student_id not in store.get_class(assignment.class_id).student_numbers:
            raise HTTPException(status_code=404, detail="生徒が見つかりません")
        store.record_action(
            assignment_id, student_id, {"action": body.action, "reason": body.reason, "duration_ms": body.duration_ms, "by": teacher}
        )
        return {"saved": True}

    @app.get("/v1/assignments/{assignment_id}/export")
    def export(assignment_id: str, teacher: str = Depends(auth.current_teacher)) -> Response:
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
            writer.writerow(
                [
                    number,
                    submission.get("status", "not_submitted"),
                    submission.get("reason") or "",
                    sum(1 for item in graded if item["correct"]) if graded else "",
                    len(graded) if graded else "",
                    record.get("action", ""),
                    record.get("duration_ms", ""),
                ]
            )
        return Response(content=output.getvalue(), media_type="text/csv; charset=utf-8")

    if os.environ.get("SERVE_WEB") == "1":
        app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "web", html=True), name="web")
    return app
