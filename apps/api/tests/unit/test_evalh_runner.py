"""評価ハーネス全体。コードは構文を読むだけで実行しないので単体テストに置く。"""
import json

import pytest

from evalh.__main__ import main
from evalh.cases import load_cases
from evalh.fakes import lexicon_pipeline
from evalh.pipeline import (
    CaseInput,
    CheckItem,
    Claim,
    Finding,
    PipelineResult,
    StagedPipeline,
    check_result,
    code_nodes,
)
from evalh.runner import EvalConfig, evaluate

DEV = load_cases(split="dev")


class OraclePipeline:
    """正解を知っている流れ。指標の計算が満点を出せることを確かめるためだけに使う。"""

    name = "oracle"

    def __init__(self, cases):
        self._gold = {case.id: case.claims for case in cases}

    def run(self, case: CaseInput) -> PipelineResult:
        nodes = code_nodes(case.code)
        claims, findings, items = [], [], []
        for gold in self._gold[case.case_id]:
            claims.append(Claim(gold.id, gold.text))
            if gold.is_gap:
                findings.append(Finding(gold.id, "file", (("file", 0.0),)))
            else:
                line = next(n for n in nodes if n.id == f"line:{gold.evidence[0][0]}")
                findings.append(Finding(gold.id, line.id, (("file", 1.0), (line.parent, 1.0), (line.id, 1.0))))
            items.append(CheckItem(gold.id, f"「{gold.text[:20]}」を説明してもらう"))
        return PipelineResult(nodes, claims, findings, items)


def test_oracle_gets_full_marks():
    report = evaluate(OraclePipeline(DEV), DEV)
    assert report["decomposition"]["f1"] == 1.0
    assert report["retrieval"]["hit_at_1"] == 1.0
    assert report["calibration"]["brier"] == 0.0
    assert report["guardrails"]["violations"] == 0
    assert report["failures"] == []
    gaps = report["budget"]["gaps"]
    assert gaps == sum(claim.is_gap for case in DEV for claim in case.claims)
    by_budget = {row["budget_sec"]: row for row in report["budget"]["ranked"]}
    assert by_budget[300]["recall"] == 1.0 and by_budget[60]["precision"] == 1.0


def test_fake_pipeline_is_deterministic_and_reports_failures():
    first = evaluate(lexicon_pipeline(), DEV)
    assert first == evaluate(lexicon_pipeline(), DEV)
    assert first["failures"], "偽物は満点にならず、失敗例が出るはず"
    assert {f["kind"] for f in first["failures"]} <= {
        "missed_gap", "false_alarm", "wrong_evidence", "missed_claim", "extra_claim", "guardrail"
    }
    assert first["guardrails"]["violations"] == 0


def test_feedback_is_skipped_when_too_few_claims():
    one = [case for case in DEV if len(case.claims) < 4][:1]
    assert evaluate(OraclePipeline(one), one, EvalConfig())["feedback"] is None
    assert evaluate(OraclePipeline(DEV), DEV)["feedback"]["dispositions"] == sum(len(c.claims) for c in DEV) // 2


def test_code_nodes_build_file_block_line_hierarchy():
    nodes = code_nodes("def f(x):\n    return x\n\nprint(f(1))\n")
    assert [(n.id, n.parent) for n in nodes] == [
        ("file", None),
        ("block:1-2", "file"),
        ("line:1", "block:1-2"),
        ("line:2", "block:1-2"),
        ("block:4-4", "file"),
        ("line:4", "block:4-4"),
    ]
    assert [n.id for n in code_nodes("def broken(:\n")] == ["file", "block:1-1", "line:1"]


def test_strength_is_product_of_path_and_missing_evidence_is_certain():
    finding = Finding("p1", "line:3", (("file", 0.9), ("block:1-3", 0.8), ("line:3", 0.2)))
    assert finding.s == pytest.approx(0.144)
    assert finding.p == pytest.approx(0.856)
    assert Finding("p1", None).p == 1.0


def test_items_without_evidence_are_not_written():
    class NoEvidence:
        def find(self, claim, nodes):
            return Finding(claim.id, None)

    class Split:
        def decompose(self, explanation, code):
            return [Claim("p1", explanation)]

    pipeline = StagedPipeline("t", Split(), NoEvidence(), writer=None)
    result = pipeline.run(CaseInput("x", "print(1)\n", "1を表示した", ""))
    assert result.items == []


def test_broken_pipeline_output_is_rejected():
    nodes = code_nodes("print(1)\n")
    with pytest.raises(ValueError):
        check_result(PipelineResult(nodes, [Claim("p1", "a")], [Finding("p9", None)]))
    with pytest.raises(ValueError):
        check_result(PipelineResult(nodes, [Claim("p1", "a")], [Finding("p1", "line:99", (("line:99", 0.5),))]))
    with pytest.raises(ValueError):
        check_result(PipelineResult(nodes, [Claim("p1", "a")], [Finding("p1", "line:1", (("line:1", 1.5),))]))


def test_cli_writes_json_and_markdown(tmp_path):
    out, md = tmp_path / "report.json", tmp_path / "report.md"
    assert main(["--split", "heldout", "--pipeline", "evalh.fakes:lexicon_pipeline", "--out", str(out), "--md", str(md)]) == 0
    reports = json.loads(out.read_text(encoding="utf-8"))
    assert reports[0]["splits"] == ["heldout"]
    assert "評価ハーネスの結果" in md.read_text(encoding="utf-8")
