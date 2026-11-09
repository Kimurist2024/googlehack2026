"""問いの生成の試験。実行環境は偽物に置き換える。"""
import json

import pytest

from app import service
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


@pytest.mark.parametrize("document", [
    {},
    {"text": "日本語😀", "escaped": ['a"b', "\\", "\n", "\x00"]},
    {"values": [True, False, None, -12, 3.5], "tuple": (1, 2)},
    {None: "null key", 2.5: "number key", False: "bool key"},
    {"values": [float("nan"), float("inf"), float("-inf")]},
])
def test_document_size_keeps_the_encoded_byte_boundary(monkeypatch, document):
    before = json.dumps(document, ensure_ascii=False)
    size = len(before.encode("utf-8"))
    monkeypatch.setattr(service, "MAX_DOC_BYTES", size - 1)
    assert service._too_large(document) is True
    monkeypatch.setattr(service, "MAX_DOC_BYTES", size)
    assert service._too_large(document) is False
    monkeypatch.setattr(service, "MAX_DOC_BYTES", size + 1)
    assert service._too_large(document) is False
    assert json.dumps(document, ensure_ascii=False) == before


@pytest.mark.parametrize(("value", "error"), [
    (object(), TypeError),
    (b"bytes are not JSON", TypeError),
    ("\ud800", UnicodeEncodeError),
])
def test_document_size_does_not_skip_invalid_tail(monkeypatch, value, error):
    monkeypatch.setattr(service, "MAX_DOC_BYTES", 10)
    with pytest.raises(error):
        service._too_large({"prefix": "x" * 100, "tail": value})


def test_document_size_still_rejects_a_circular_tail(monkeypatch):
    monkeypatch.setattr(service, "MAX_DOC_BYTES", 10)
    document = {"prefix": "x" * 100}
    document["tail"] = document
    with pytest.raises(ValueError, match="Circular"):
        service._too_large(document)


@pytest.mark.parametrize("depth", [10, 100, 300, 600, 900, 950, 980, 1000])
def test_document_size_keeps_deep_nesting_behavior(depth):
    value = 0
    for _ in range(depth):
        value = [value]
    document = {"value": value}
    def previous(doc):
        return len(json.dumps(doc, ensure_ascii=False).encode("utf-8")) > service.MAX_DOC_BYTES
    try:
        expected = previous(document)
    except RecursionError:
        with pytest.raises(RecursionError):
            service._too_large(document)
    else:
        assert service._too_large(document) is expected
