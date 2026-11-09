import random

import pytest

from evalh import budget, metrics, teacher


def test_claims_are_matched_one_to_one_by_similarity():
    gold = [("g1", "60点以上のときだけ合計に足した"), ("g2", "最後に合計を表示した")]
    pred = [("p1", "最後に合計を表示しました"), ("p2", "60点以上だけ合計に足した"), ("p3", "関係のない文")]
    assert metrics.match_claims(gold, pred, 0.5) == {"g1": "p2", "g2": "p1"}


def test_prf_handles_empty_prediction():
    assert metrics.prf(0, 3, 0) == {"precision": 0.0, "recall": 0.0, "f1": 0.0, "gold": 3, "pred": 0, "matched": 0}


def test_calibration_of_perfect_and_constant_predictions():
    perfect = metrics.calibration([(1.0, 1), (0.0, 0), (0.0, 0)])
    assert perfect["brier"] == 0.0 and perfect["ece"] == 0.0
    constant = metrics.calibration([(0.5, 1), (0.5, 0)])
    assert constant["brier"] == pytest.approx(0.25)
    assert constant["ece"] == pytest.approx(0.0)
    assert metrics.calibration([])["brier"] is None


def test_guardrails_follow_the_rules_in_the_spec():
    ok = metrics.guardrail_violations("p1", "3行目：「合計に足した」を説明してもらう", True)
    assert ok == []
    kinds = {v.kind for v in metrics.guardrail_violations("p1", "理解していない" + "あ" * 80, False)}
    assert kinds == {"too_long", "no_evidence", "judging_words"}


def test_budget_matches_the_worked_example_in_the_spec():
    # 企画案 v0.6 p.19：持ち時間2分なら A・D・C（計90秒）まで見る。B は次に回す
    items = [
        budget.BudgetItem("A", "s1", 0.86, 2, 40),
        budget.BudgetItem("D", "s2", 0.50, 1, 20),
        budget.BudgetItem("C", "s3", 0.72, 1, 30),
        budget.BudgetItem("B", "s4", 0.31, 2, 40),
    ]
    assert [round(item.t) for item in sorted(items, key=lambda it: it.t)] == [23, 40, 42, 65]
    assert [item.key for item in budget.select(items, 120)] == ["A", "D", "C"]
    # 確認枠に60秒回すと、残り60秒で A（40秒）と D（20秒）まで
    assert [item.key for item in budget.select(items, 120, audit_sec=60)] == ["A", "D"]


def test_budget_takes_at_most_three_per_student():
    items = [budget.BudgetItem(f"k{n}", "same", 0.9, 1, 10) for n in range(5)]
    assert len(budget.select(items, 1000)) == 3


def test_recall_curve_and_whole_review_baseline():
    items = [budget.BudgetItem("a", "s1", 0.9, 1, 30), budget.BudgetItem("b", "s2", 0.1, 1, 30)]
    rows = budget.recall_curve(items, {"a"}, 2, [30, 60])
    assert [row["found"] for row in rows] == [1, 1]
    assert rows[0]["recall"] == 0.5 and rows[0]["precision"] == 1.0
    whole = budget.whole_review_curve({"s1": 1, "s2": 1}, 2, [149, 150, 300], 150, 1.0)
    assert [row["recall"] for row in whole] == [0.0, 0.5, 1.0]


def test_band_calibration_uses_the_formula_in_the_spec():
    dispositions = [teacher.Disposition(f"k{n}", 0.9, useful, 30) for n, useful in enumerate([True, True, True, False])]
    table = teacher.band_table(dispositions, 5)
    assert table == {4: pytest.approx((1 + 3) / (2 + 4))}
    assert teacher.calibrated(0.95, table) == pytest.approx(4 / 6)
    assert teacher.calibrated(0.1, table) == 0.1  # 処置のない帯は元のまま


def test_simulated_teacher_is_reproducible_and_noise_flips():
    rows = [("a", 0.9, True), ("b", 0.1, False)]
    exact = teacher.simulate(rows, 0.0, 30, random.Random(1))
    assert [d.useful for d in exact] == [True, False]
    flipped = teacher.simulate(rows, 1.0, 30, random.Random(1))
    assert [d.useful for d in flipped] == [False, True]
    assert teacher.simulate(rows, 0.3, 30, random.Random(7)) == teacher.simulate(rows, 0.3, 30, random.Random(7))
    assert teacher.tau_after(exact, 99) == pytest.approx((exact[0].seconds + exact[1].seconds) / 2)
    assert teacher.tau_after([], 99) == 99
