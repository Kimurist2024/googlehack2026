import pytest

from app.ordering import Candidate, calibrated_p, rank, tau_from, weight_of, within_budget


def test_matches_the_worked_example_in_the_spec():
    candidates = [
        Candidate("A", ("impact", "impact", "impact"), 3),
        Candidate("B", ("output", "output"), 3),
        Candidate("C", ("impact",), 3),
        Candidate("D", (), 3),
    ]
    ranked = rank(candidates, {"impact": 2.0, "output": 1.0}, 30.0)
    assert [item.student_id for item in ranked] == ["A", "C", "B", "D"]
    assert [round(item.t) for item in ranked] == [19, 38, 50, 150]
    assert [item.student_id for item in within_budget(ranked, 90)] == ["A", "C", "B"]


def test_all_correct_is_not_zero():
    assert calibrated_p(0, 3) == pytest.approx(0.2)


def test_weight_is_mean_of_wrong_types_and_one_when_none():
    assert weight_of(("a", "b"), {"a": 3.0, "b": 1.0}) == 2.0
    assert weight_of((), {"a": 3.0}) == 1.0


def test_tau_uses_median_of_recorded_durations():
    assert tau_from([]) == 30.0
    assert tau_from([10, 20, 90]) == 20.0


def test_budget_smaller_than_one_student_selects_none():
    ranked = rank([Candidate("A", ("x",), 3)], {}, 30.0)
    assert within_budget(ranked, 10) == []
