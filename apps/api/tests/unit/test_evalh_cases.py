"""模擬提出物と正解そのものの検査。正解が壊れていると、評価の数字が全部あてにならなくなる。"""
import json

import pytest

from evalh.cases import load_cases

ALL = load_cases(split=None)


def test_both_splits_have_gaps_and_non_gaps():
    for split in ("dev", "heldout"):
        claims = [claim for case in ALL if case.split == split for claim in case.claims]
        assert any(claim.is_gap for claim in claims), split
        assert any(not claim.is_gap for claim in claims), split


def test_splits_do_not_overlap():
    dev = {case.id for case in load_cases(split="dev")}
    heldout = {case.id for case in load_cases(split="heldout")}
    assert dev and heldout and not dev & heldout
    assert dev | heldout == {case.id for case in ALL}


@pytest.mark.parametrize("case", ALL, ids=lambda case: case.id)
def test_gold_claims_point_at_real_code(case):
    lines = case.input.code.splitlines()
    assert len({claim.id for claim in case.claims}) == len(case.claims)
    for claim in case.claims:
        assert claim.text in case.input.explanation, claim.id
        for start, end in claim.evidence:
            assert 1 <= start <= end <= len(lines), claim.id
            assert any(lines[n - 1].strip() for n in range(start, end + 1)), claim.id


def test_loader_rejects_gap_with_evidence(tmp_path):
    folder = tmp_path / "x01"
    folder.mkdir()
    (folder / "program.py").write_text("print(1)\n", encoding="utf-8")
    (folder / "explanation.txt").write_text("1を表示した。\n", encoding="utf-8")
    gold = {"split": "dev", "claims": [{"id": "g1", "text": "1を表示した", "label": "gap", "evidence": [[1, 1]]}]}
    (folder / "gold.json").write_text(json.dumps(gold), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(tmp_path, "dev")


def test_unknown_split_is_rejected():
    with pytest.raises(ValueError):
        load_cases(split="test")


def test_weak_students_keep_the_same_code_labels_and_evidence():
    from evalh.cases import load_cases

    for split in ("dev", "heldout"):
        standard, weak = load_cases(split=split), load_cases(split=split, student="weak")
        assert [c.id for c in standard] == [c.id for c in weak]
        for a, b in zip(standard, weak):
            assert a.input.code == b.input.code and a.input.explanation != b.input.explanation
            assert [(g.id, g.label, g.kind, g.evidence) for g in a.claims] == [(g.id, g.label, g.kind, g.evidence) for g in b.claims]
            assert all(g.text in b.input.explanation for g in b.claims)


def test_unknown_student_level_is_rejected():
    import pytest

    from evalh.cases import load_cases

    with pytest.raises(ValueError):
        load_cases(student="genius")


def test_low_quality_set_loads_and_keeps_its_splits():
    """小さなモデルが書いた提出物（evals/cases_lowq）。正解は人が付け、動きの主張は作るときに実行で確かめてある。"""
    from evalh.cases import DEFAULT_DIR, load_cases

    folder = DEFAULT_DIR.parent / "cases_lowq"
    dev, held = load_cases(folder, split="dev"), load_cases(folder, split="heldout")
    assert len(dev) == 14 and len(held) == 6
    assert sum(g.is_gap and g.kind == "behavior" for case in dev for g in case.claims) == 10


def test_low_quality_v2_set_has_execution_checks_for_every_behavior_claim():
    """evals/cases_lowq2：コードは小さなモデル、説明は型から作り、動きの主張の正解は実行で決めてある。"""
    import json

    from evalh.cases import DEFAULT_DIR, load_cases

    folder = DEFAULT_DIR.parent / "cases_lowq2"
    dev, held = load_cases(folder, split="dev"), load_cases(folder, split="heldout")
    assert len(dev) >= 40 and len(held) >= 20
    # 課題ごとに dev と heldout を分けている（同じ課題の提出物が両方に入らない）
    assert not {c.id.split("_")[0] for c in dev} & {c.id.split("_")[0] for c in held}
    for case in dev + held:
        raw = json.loads((folder / case.id / "gold.json").read_text(encoding="utf-8"))["claims"]
        assert all("check" in c for c in raw if c["kind"] == "behavior"), case.id
