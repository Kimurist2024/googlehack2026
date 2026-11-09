"""問いの生成、採点、声をかける順の処理。"""
import ast
import io
import json
import logging
import re
import time
import zipfile
import zlib

from qgen import probes
from qgen.ai import QuizAI
from qgen.questions import IMPACT, OUTPUT, TRACE, build_candidates, seeded_random
from qgen.sandbox import Sandbox, SandboxError

from . import insight
from .ordering import Candidate, Ranked, rank, tau_from, within_budget
from .store import AssignmentRecord, ClassRecord, Store

logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_FILES = 500
# Firestore の1文書の上限は 1MiB。余裕を見て、超えそうな提出は対象外にする
MAX_DOC_BYTES = 900_000
# 解答した生徒がこれより少ないと、まとめから個人がわかりやすいので作らない
MIN_STUDENTS_FOR_SUMMARY = 3
TYPE_LABELS = {OUTPUT: "出力の予測", TRACE: "変数の追跡", IMPACT: "変更の影響"}
# 振り返りの質問は1人1課題あたりこの回数まで。Gemini の費用を抑える
CHAT_LIMIT = 10
RESULT_NOTICE = "この結果は成績には使いません。"
# 隔離環境が返す理由のうち、保存して画面やCSVに出してよいもの。隔離環境の出力は信用しない
EXCLUSION_REASONS = {
    "syntax_error",
    "unsupported_import",
    "unsupported_code",
    "timeout",
    "too_long",
    "error",
    "too_much_output",
    "nondeterministic",
}


def _read_entry(archive: zipfile.ZipFile, entry: zipfile.ZipInfo) -> bytes | None:
    """1つのファイルを上限まで読む。ヘッダーの大きさは偽れるので、実際に読んだ量で確かめる（zip爆弾対策）。"""
    with archive.open(entry) as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    return None if len(data) > MAX_FILE_BYTES else data


def read_submissions(data: bytes, known_numbers: set[str]) -> tuple[dict[str, str], list[str]]:
    """zipを展開せずに読む。ファイル名の出席番号で名簿と対応づける。"""
    found: dict[str, str] = {}
    problems: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, EOFError):
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
        if number in found:
            problems.append(f"{name}: 同じ番号のファイルが複数あります。最初のものを使います")
            continue
        if entry.flag_bits & 0x1:
            problems.append(f"{name}: パスワード付きのファイルは読めません")
            continue
        if entry.file_size > MAX_FILE_BYTES:
            problems.append(f"{name}: 大きすぎます")
            continue
        try:
            content = _read_entry(archive, entry)
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, ValueError):
            problems.append(f"{name}: 壊れているため読めません")
            continue
        if content is None:
            problems.append(f"{name}: 大きすぎます")
            continue
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("合計サイズが大きすぎます")
        try:
            found[number] = content.decode("utf-8")
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
        reason = result.get("status")
        return {"status": "excluded", "reason": reason if reason in EXCLUSION_REASONS else "error"}
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
                "line": item.get("line"),
            }
        )
    return graded


def deadline(attempt: dict, assignment: AssignmentRecord) -> float:
    """持ち時間が終わる時刻。サーバーの時計で始めた時刻から数える。"""
    return attempt["started_at"] + assignment.time_limit_sec


def score(graded: list[dict]) -> int:
    """採点結果から正答数を数える。"""
    return sum(1 for item in graded if item["correct"])


def result_view(graded: list[dict], key: dict) -> dict:
    """生徒に返す採点結果と実行の記録をまとめる。"""
    return {
        "score": score(graded),
        "total": len(graded),
        "results": graded,
        "trace": key["trace"],
        "notice": RESULT_NOTICE,
    }


def lined_items(attempt: dict, key: dict) -> list[dict]:
    """採点結果に、問いが指す行を添える。行は解答の前に保存した正解の側から取る。"""
    return [
        {"type": item["type"], "stem": item["stem"], "correct": item["correct"], "line": key["questions"][item["id"]].get("line")}
        for item in attempt["graded"]
    ]


def explainable_lines(attempt: dict, key: dict) -> list[int]:
    """生徒に自分の言葉で説明してもらう行。誤答した問いが指す行だけにする。"""
    return sorted({item["line"] for item in lined_items(attempt, key) if not item["correct"] and item["line"]})


# 生徒の説明のうち、コードを動かして確かめる文の数。1文ごとに Gemini と隔離環境を1回ずつ使う
MAX_CHECKED_SENTENCES = 4
SHOWN_CHARS = 80


def sentences(text: str) -> list[str]:
    """説明を文に分ける。句点・感嘆符・疑問符・改行で切る。"""
    return [part.strip() for part in re.split(r"(?<=[。！？!?])|\n", text) if part and part.strip()]


def _short(text: object) -> str:
    text = str(text)
    return text if len(text) <= SHOWN_CHARS else text[: SHOWN_CHARS - 1] + "…"


def describe_run(probe: probes.Probe, outcome: dict) -> dict:
    """試したこと・説明から読み取った結果・実際の結果を、教員が読める文にする。"""
    if probe.kind == "call":
        try:
            values = ast.literal_eval(probe.args)
            shown_args = ", ".join(repr(value) for value in values)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            shown_args = probe.args
        tried = f"{probe.function}({shown_args})"
        if probe.expect_kind == "raises":
            expected = "エラーになる" if probe.expect_value == "true" else "エラーにならない"
        else:
            expected = f"{probe.expect_value} を返す"
        actual = f"{outcome.get('raised')} のエラー" if outcome.get("raised") else f"{outcome.get('returned')} を返した"
    else:
        stdin = probe.stdin.strip().replace("\n", " / ")
        tried = f"入力 {stdin} で実行" if stdin else "実行"
        shown = probe.expect_value.strip() in [line.strip() for line in str(outcome.get("stdout", "")).splitlines()]
        expected = f"「{probe.expect_value}」の行が表示{'される' if probe.expect_kind == 'stdout_line' else 'されない'}"
        actual = f"「{probe.expect_value}」の行は表示{'された' if shown else 'されなかった'}"
    return {"tried": _short(tried), "expected": _short(expected), "actual": _short(actual)}


def check_explanation(
    store: Store, sandbox: Sandbox, planner: probes.ProbePlanner, assignment_id: str, student_id: str, line: int, text: str
) -> list[dict]:
    """生徒が書いた説明のうち、動きについての文を、本人のコードを動かして確かめる。

    何を試すかは planner（規則か Gemini）が決め、説明どおりかは probes.verdict が機械的に決める。
    確かめられなかった文は残さない。結果は、生徒がその後に書き直していなければ保存する。
    """
    quiz = store.get_quiz(assignment_id, student_id)
    attempt = store.get_attempt(assignment_id, student_id) or {}
    if quiz is None:
        return []
    done = (attempt.get("explanation_checks") or {}).get(str(line))
    if done and done.get("text") == text:  # 同じ文をもう一度送っただけなら、Gemini と隔離環境を使い直さない
        return done["checks"]
    code = quiz["code"]
    checks = []
    for sentence in sentences(text)[:MAX_CHECKED_SENTENCES]:
        planned = planner.plan(sentence, code)
        if not planned:
            continue
        try:
            result = sandbox.probe(code, [probe.request() for probe in planned])
        except SandboxError:
            logger.warning("説明を確かめる実行に失敗しました")
            continue
        outcomes = result.get("probes", []) if result.get("status") == "ok" else []
        if len(outcomes) != len(planned):
            continue
        verdicts = [probes.verdict(probe, outcome) for probe, outcome in zip(planned, outcomes)]
        overall = probes.combine(verdicts)
        if overall == probes.UNKNOWN:
            continue
        runs = [describe_run(probe, outcome) | {"verdict": v} for probe, outcome, v in zip(planned, outcomes, verdicts) if v != probes.UNKNOWN]
        checks.append({"sentence": _short(sentence), "verdict": overall, "runs": runs})
    store.save_explanation_checks(assignment_id, student_id, line, text, checks)
    return checks


def create_followups(store: Store, assignment: AssignmentRecord, ai: QuizAI) -> None:
    """締切のあと、生徒ごとに記録を足し、本人の説明を聞きたい行と、教員がたずねる質問案を作る。

    どの行を聞くかと根拠は、採点結果、これまでの記録、クラスの提出から機械的に決める。AIは質問の言い回しと
    これまでの様子のまとめだけを書く。
    """
    existing = store.followups(assignment.id)
    submissions = store.submissions(assignment.id)
    usage = insight.class_usage([doc["code"] for doc in submissions.values()])
    closed_at = now()
    for student_id, attempt in store.attempts(assignment.id).items():
        if attempt.get("submitted_at") is None:
            continue
        code = store.get_quiz(assignment.id, student_id)["code"]
        items = lined_items(attempt, store.get_answer_key(assignment.id, student_id))
        record = store.get_student_record(assignment.class_id, student_id) or {}
        previous = [entry for entry in record.get("entries", []) if entry["assignment_id"] != assignment.id]
        seen = {label for entry in previous for label in entry.get("constructs", [])}
        spots = insight.find_spots(code, items, seen, bool(previous), usage, len(submissions))
        recurring = insight.recurring_constructs(previous, spots)
        done = existing.get(student_id, {})
        if spots and not done.get("review"):
            review = ai.review(code, insight.history_for_ai(previous), spots, recurring)
            for spot, ask in zip(spots, review["asks"]):
                spot["question"] = ask
            stored = {"overview": review["overview"], "spots": spots, "recurring": recurring, "by": review["by"]}
            store.add_followup(assignment.id, student_id, spots[0]["question"], spots[0]["line"], stored)
        elif done.get("review"):
            spots = done["review"]["spots"]
        store.save_student_entry(
            assignment.class_id,
            student_id,
            {
                "assignment_id": assignment.id,
                "title": assignment.title,
                "closed_at": closed_at,
                # 元の課題と同じ期限で、記録からも消える（生徒のデータの保存期間をそろえる）
                "expire_at": assignment.expire_at,
                "score": score(items),
                "total": len(items),
                "wrong_types": sorted({item["type"] for item in items if not item["correct"]}),
                "constructs": insight.constructs_in(code),
                "spots": [{key: spot.get(key) for key in ("line", "code", "constructs", "new", "rare", "unexplained", "question")} for spot in spots],
                "action": {"action": done["action"], "reason": done.get("reason", "")} if done.get("action") else None,
            },
        )


def class_stats(attempts: dict[str, dict]) -> tuple[list[dict], list[dict], int]:
    """問いの種類ごとに、解答した人数と誤答した人数を数える。AI は使わない。"""
    submitted = [attempt for attempt in attempts.values() if attempt.get("submitted_at") is not None]
    stats = []
    for kind, label in TYPE_LABELS.items():
        answered = wrong = 0
        for attempt in submitted:
            items = [item for item in attempt["graded"] if item["type"] == kind]
            if items:
                answered += 1
                wrong += any(not item["correct"] for item in items)
        if answered:
            stats.append({"type": kind, "label": label, "answered": answered, "wrong": wrong})
    wrong_items = [
        {"type": item["type"], "stem": item["stem"], "answer": item["answer"], "given": item["given"]}
        for attempt in submitted
        for item in attempt["graded"]
        if not item["correct"]
    ]
    return stats, wrong_items, len(submitted)


def create_class_summary(store: Store, assignment: AssignmentRecord, ai: QuizAI) -> None:
    """締切のあと、クラス全体のつまずきをまとめる。人数の集計は AI を使わずに出す。"""
    stats, wrong_items, students = class_stats(store.attempts(assignment.id))
    if students < MIN_STUDENTS_FOR_SUMMARY:
        return
    summary = ai.class_summary(stats, wrong_items)
    store.set_class_summary(assignment.id, {**summary, "stats": stats, "students": students})


def chat_context(store: Store, assignment_id: str, student_id: str, attempt: dict) -> dict:
    """振り返りの対話に渡す材料。本人のコード、結果、実行の記録だけを使う。"""
    quiz = store.get_quiz(assignment_id, student_id)
    key = store.get_answer_key(assignment_id, student_id)
    results = [
        {
            "stem": item["stem"],
            "given": item["given"],
            "answer": item["answer"],
            "correct": item["correct"],
            "line": key["questions"][item["id"]].get("line"),
        }
        for item in attempt["graded"]
    ]
    return {"code": quiz["code"], "stdin": quiz["stdin"], "results": results, "trace": key["trace"][:80]}


def current_checks(attempt: dict) -> dict[str, list[dict]]:
    explanations = attempt.get("explanations") or {}
    return {
        line: saved["checks"]
        for line, saved in (attempt.get("explanation_checks") or {}).items()
        if saved.get("checks") and explanations.get(line) == saved.get("text")
    }


def _followup_row(item: Ranked, number: str, attempt: dict, record: dict, in_budget: bool) -> dict:
    """採点結果と声かけの記録を、生徒1人分の表示にまとめる。"""
    return {
        "student_id": item.student_id,
        "number": number,
        "t_sec": round(item.t, 1),
        "score": score(attempt["graded"]),
        "total": len(attempt["graded"]),
        "in_budget": in_budget,
        "question": record.get("question"),
        "review": record.get("review"),
        "memo": record.get("memo"),  # 以前の形の声かけメモ。新しい締切では作らない
        # 生徒が自分の言葉で書いた説明。行番号（文字列）-> 本文
        "explanations": attempt.get("explanations") or {},
        # 説明の文を本人のコードで動かして確かめた結果。生徒がその後に書き直した行のものは出さない
        "explanation_checks": current_checks(attempt),
        # 根拠は AI ではなく採点結果からそのまま出す
        "evidence": [{"stem": g["stem"], "given": g["given"], "answer": g["answer"]} for g in attempt["graded"] if not g["correct"]],
        "action": record.get("action"),
    }


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
            _followup_row(item, classroom.student_numbers[item.student_id], attempt, record, item.student_id in in_budget)
        )
    return {
        "tau_sec": tau,
        "budget_sec": budget_sec,
        "order": rows,
        "excluded": excluded,
        "not_attempted": not_attempted,
        "class_summary": assignment.class_summary,
        "summary_min_students": MIN_STUDENTS_FOR_SUMMARY,
    }


def student_record_view(store: Store, classroom: ClassRecord, student_id: str) -> dict:
    """教員が見る、生徒ごとのこれまでの記録。新しい課題から並べる。"""
    record = store.get_student_record(classroom.id, student_id) or {}
    entries = sorted(record.get("entries", []), key=lambda entry: entry.get("closed_at", 0), reverse=True)
    return {"number": classroom.student_numbers[student_id], "entries": entries}


def now() -> float:
    return time.time()
