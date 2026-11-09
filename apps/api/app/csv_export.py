"""生徒の結果を表計算ソフトで開けるCSVにする。"""
import csv
import io

from . import service

# 表計算ソフトが数式として実行してしまう先頭の文字（CSV インジェクション）
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: object) -> object:
    """表計算ソフトで開いたときに数式として動かないようにする。"""
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def build_csv(
    student_numbers: dict[str, str], submissions: dict[str, dict], attempts: dict[str, dict], followups: dict[str, dict]
) -> str:
    """名簿の順に提出状況、採点結果、声かけの記録を並べる。"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["number", "status", "reason", "score", "total", "action", "duration_ms"])
    for student_id, number in student_numbers.items():
        submission = submissions.get(student_id, {})
        attempt = attempts.get(student_id, {})
        graded = attempt.get("graded", [])
        record = followups.get(student_id, {})
        row = [
            number,
            submission.get("status", "not_submitted"),
            submission.get("reason") or "",
            service.score(graded) if graded else "",
            len(graded) if graded else "",
            record.get("action", ""),
            record.get("duration_ms", ""),
        ]
        writer.writerow([csv_cell(value) for value in row])
    return output.getvalue()
