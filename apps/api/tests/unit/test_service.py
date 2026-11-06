"""問いの生成の試験。実行環境は偽物に置き換える。"""
from app.service import generate_one
from app.store import AssignmentRecord
from qgen.ai import TemplateAI


class FixedSandbox:
    def __init__(self, result):
        self.result = result

    def analyze(self, code, stdin):
        return self.result


ASSIGNMENT = AssignmentRecord("a", "c", "合計", "", [], 300, 3, {"output": 1.0})


def result_with_values(size: int) -> dict:
    history = [{"scope": "", "name": "x", "value": repr("a" * size + str(i)), "line": 1} for i in range(3)]
    return {"status": "ok", "stdout": "1\n", "history": history, "mutants": []}


def test_ordinary_result_is_ready():
    outcome = generate_one(ASSIGNMENT, "s1", "x = 1\n", FixedSandbox(result_with_values(10)), TemplateAI())
    assert outcome["status"] == "ready"
    assert "answer" not in outcome["quiz"]["questions"][0]
    assert outcome["answer_key"]["questions"]


def test_result_too_large_for_one_document_is_excluded():
    outcome = generate_one(ASSIGNMENT, "s1", "x = 1\n", FixedSandbox(result_with_values(400_000)), TemplateAI())
    assert outcome == {"status": "excluded", "reason": "too_much_output"}
