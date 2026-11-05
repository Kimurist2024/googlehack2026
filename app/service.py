"""問いの生成、採点、声をかける順の処理。"""
import io
import json
import logging
import re
import time
import zipfile

from qgen.ai import QuizAI
from qgen.questions import Question, build_candidates, seeded_random
from qgen.sandbox import Sandbox

from .ordering import Candidate, rank, tau_from, within_budget
from .store import AssignmentRecord, ClassRecord, Store

logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_FILES = 500
# Firestore の1文書の上限は 1MiB。余裕を見て、超えそうな提出は対象外にする
MAX_DOC_BYTES = 900_000


def read_submissions(data: bytes, known_numbers: set[str]) -> tuple[dict[str, str], list[str]]:
    """zipを展開せずに読む。ファイル名の出席番号で名簿と対応づける。"""
    found: dict[str, str] = {}
    problems: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("zipファイルとして読めません") from None
    entries = [entry for entry in archive.infolist() if not entry.is_dir()]
    if len(entries) > MAX_FILES:
        raise ValueError(f"ファイル数が多すぎます（上限 {MAX_FILES}）")
    total = 0
    for entry in entries:
        name = entry.filename.rsplit("/", 1)[-1]
        if name.startswith(".") or entry.filename.startswith("__MACOSX/"):
            continue
        match = re.fullmatch(r"(.+)\.py", name)
        if not match:
            problems.append(f"{name}: .py 以外は読みません")
            continue
        number = match.group(1)
        if number not in known_numbers:
            problems.append(f"{name}: 名簿にない番号です")
            continue
        if entry.file_size > MAX_FILE_BYTES:
            problems.append(f"{name}: 大きすぎます")
            continue
        total += entry.file_size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("合計サイズが大きすぎます")
        try:
            found[number] = archive.read(entry).decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{name}: UTF-8 で読めません")
    return found, problems


def choose_stdin(examples: list[str], assignment_id: str, student_id: str) -> str:
    if not examples:
        return ""
    return seeded_random(assignment_id, student_id, "stdin").choice(examples)


def _too_large(document: dict) -> bool:
    return len(json.dumps(document, ensure_ascii=False).encode("utf-8")) > MAX_DOC_BYTES


def generate_one(assignment: AssignmentRecord, student_id: str, code: str, sandbox: Sandbox, ai: QuizAI) -> dict:
    """提出1件の問いを作る。戻り値は保存する内容。"""
    stdin = choose_stdin(assignment.stdin_examples, assignment.id, student_id)
    seed = f"{assignment.id}:{student_id}"
    try:
        result = sandbox.analyze(code, stdin)
    except Exception:  # API の一時的な失敗なども含め、1件の失敗で全体を止めない
        logger.exception("実行環境の失敗 student=%s", student_id)
        return {"status": "failed", "reason": "sandbox_error"}
    if result.get("status") != "ok":
        return {"status": "excluded", "reason": result.get("status")}
    candidates = build_candidates(result, stdin, seed)
    count = min(assignment.question_count, len(candidates))
    if count == 0:
        return {"status": "excluded", "reason": "no_questions"}
    chosen = ai.select(assignment.learning_goal, code, candidates, count, seed)
    keys = {}
    for question in chosen:
        keys[question.id] = {**question.to_dict(), "explanation": ai.explain(question)}
    quiz = {"questions": [question.public() for question in chosen], "code": code, "stdin": stdin}
    answer_key = {
        "questions": keys,
        "trace": [f"{e['line']}行目: {e['name']} = {e['value']}" for e in result.get("history", [])[:200]],
    }
    if _too_large(quiz) or _too_large(answer_key):
        return {"status": "excluded", "reason": "too_much_output"}
    return {"status": "ready", "quiz": quiz, "answer_key": answer_key}


def generate_all(store: Store, assignment: AssignmentRecord, sandbox: Sandbox, ai: QuizAI) -> None:
    for student_id, submission in store.submissions(assignment.id).items():
        outcome = generate_one(assignment, student_id, submission["code"], sandbox, ai)
        store.save_generation_result(
            assignment.id, student_id, outcome["status"], outcome.get("reason"), outcome.get("quiz"), outcome.get("answer_key")
        )
    store.end_generation(assignment.id, "ready")


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def grade(key: dict, answers: dict[str, str]) -> list[dict]:
    graded = []
    for question_id, item in key["questions"].items():
        given = str(answers.get(question_id, ""))
        graded.append(
            {
                "id": question_id,
                "type": item["type"],
                "stem": item["stem"],
                "given": given,
                "answer": item["answer"],
                "correct": normalized(given) == normalized(item["answer"]) and bool(given.strip()),
                "explanation": item["explanation"],
            }
        )
    return graded


def create_followups(store: Store, assignment: AssignmentRecord, ai: QuizAI) -> None:
    """締切のあと、誤答のあった生徒ごとに授業で聞く一問を作る。"""
    existing = store.followups(assignment.id)
    for student_id, attempt in store.attempts(assignment.id).items():
        if attempt.get("submitted_at") is None:
            continue
        wrong = [item for item in attempt["graded"] if not item["correct"]]
        if not wrong or student_id in existing:
            continue
        keys = store.get_answer_key(assignment.id, student_id)["questions"]
        # 行を示せる誤答を優先する。教員が具体的に聞きやすくなる
        item = next((entry for entry in wrong if keys[entry["id"]].get("line")), wrong[0])
        question = Question(**{k: v for k, v in keys[item["id"]].items() if k != "explanation"})
        store.add_followup_question(assignment.id, student_id, ai.followup(question, item["given"]), question.line)


def followup_view(store: Store, assignment: AssignmentRecord, classroom: ClassRecord, budget_sec: float) -> dict:
    submissions = store.submission_statuses(assignment.id)
    attempts = store.attempts(assignment.id)
    followups = store.followups(assignment.id)
    durations = [record["duration_ms"] / 1000 for record in followups.values() if record.get("duration_ms")]
    tau = tau_from(durations)
    candidates, excluded, not_attempted = [], [], []
    for student_id, number in classroom.student_numbers.items():
        submission = submissions.get(student_id)
        if submission is None or submission.get("status") != "ready":
            excluded.append({"number": number, "reason": submission.get("reason") if submission else "not_submitted"})
            continue
        attempt = attempts.get(student_id)
        if attempt is None or attempt.get("submitted_at") is None:
            not_attempted.append({"number": number})
            continue
        wrong = tuple(item["type"] for item in attempt["graded"] if not item["correct"])
        candidates.append(Candidate(student_id, wrong, len(attempt["graded"])))
    ranked = rank(candidates, assignment.weights, tau)
    # 処置が済んだ生徒に持ち時間は使わない。残りの生徒だけで計算する
    pending = [item for item in ranked if not followups.get(item.student_id, {}).get("action")]
    in_budget = {item.student_id for item in within_budget(pending, budget_sec)}
    rows = []
    for item in ranked:
        record = followups.get(item.student_id, {})
        attempt = attempts[item.student_id]
        rows.append(
            {
                "student_id": item.student_id,
                "number": classroom.student_numbers[item.student_id],
                "t_sec": round(item.t, 1),
                "score": sum(1 for g in attempt["graded"] if g["correct"]),
                "total": len(attempt["graded"]),
                "in_budget": item.student_id in in_budget,
                "question": record.get("question"),
                "action": record.get("action"),
            }
        )
    return {"tau_sec": tau, "budget_sec": budget_sec, "order": rows, "excluded": excluded, "not_attempted": not_attempted}


def now() -> float:
    return time.time()
