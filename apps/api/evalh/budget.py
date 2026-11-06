"""持ち時間の中で確かめる順番と、そのとき拾える理解不足の割合。

t = τ ÷ (p̃ × w) の短い順に、Στ ≤ B − 確認枠の時間 まで、1人3件までを選ぶ（企画案 v0.6）。
比べる相手は「出席番号順に提出物を丸ごと見る」やり方。
"""
from dataclasses import dataclass

MIN_P = 1e-6
MAX_PER_STUDENT = 3


@dataclass(frozen=True)
class BudgetItem:
    key: str
    student: str
    p: float
    weight: float
    tau: float

    @property
    def t(self) -> float:
        return self.tau / (max(self.p, MIN_P) * self.weight)


def select(items: list[BudgetItem], budget_sec: float, audit_sec: float = 0.0, per_student: int = MAX_PER_STUDENT) -> list[BudgetItem]:
    chosen, used, counts = [], 0.0, {}
    for item in sorted(items, key=lambda it: (it.t, it.student, it.key)):
        if counts.get(item.student, 0) >= per_student:
            continue
        if used + item.tau > budget_sec - audit_sec:
            break
        chosen.append(item)
        used += item.tau
        counts[item.student] = counts.get(item.student, 0) + 1
    return chosen


def recall_curve(items: list[BudgetItem], gap_keys: set[str], total_gaps: int, budgets: list[float], audit_sec: float = 0.0) -> list[dict]:
    rows = []
    for budget in budgets:
        chosen = select(items, budget, audit_sec)
        hits = sum(1 for item in chosen if item.key in gap_keys)
        rows.append({
            "budget_sec": budget,
            "items": len(chosen),
            "found": hits,
            "recall": hits / total_gaps if total_gaps else None,
            "precision": hits / len(chosen) if chosen else None,
        })
    return rows


def whole_review_curve(gaps_by_student: dict[str, int], total_gaps: int, budgets: list[float], per_submission_sec: float, find_rate: float) -> list[dict]:
    """出席番号順に1件ずつ丸ごと見たとき。見た提出物の理解不足を find_rate の割合で見つけるとする。"""
    order = sorted(gaps_by_student)
    rows = []
    for budget in budgets:
        seen = order[: int(budget // per_submission_sec)]
        found = find_rate * sum(gaps_by_student[student] for student in seen)
        rows.append({
            "budget_sec": budget,
            "submissions": len(seen),
            "found": found,
            "recall": found / total_gaps if total_gaps else None,
        })
    return rows
