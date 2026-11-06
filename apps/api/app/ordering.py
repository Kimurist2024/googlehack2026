"""教員が声をかける順の計算。AIは使わない。"""
from dataclasses import dataclass
from statistics import median

DEFAULT_TAU_SEC = 30.0


@dataclass(frozen=True)
class Candidate:
    student_id: str
    wrong_types: tuple[str, ...]
    question_count: int


@dataclass(frozen=True)
class Ranked:
    student_id: str
    p: float
    weight: float
    tau: float
    t: float


def calibrated_p(wrong: int, total: int) -> float:
    """全問正解でも0にならない確率。順番の最後には残す。"""
    return (1 + wrong) / (2 + total)


def weight_of(wrong_types: tuple[str, ...], weights: dict[str, float]) -> float:
    if not wrong_types:
        return 1.0
    return sum(weights.get(kind, 1.0) for kind in wrong_types) / len(wrong_types)


def tau_from(durations_sec: list[float]) -> float:
    return float(median(durations_sec)) if durations_sec else DEFAULT_TAU_SEC


def rank(candidates: list[Candidate], weights: dict[str, float], tau: float) -> list[Ranked]:
    ranked = []
    for candidate in candidates:
        p = calibrated_p(len(candidate.wrong_types), candidate.question_count)
        weight = weight_of(candidate.wrong_types, weights)
        ranked.append(Ranked(candidate.student_id, p, weight, tau, tau / (p * weight)))
    return sorted(ranked, key=lambda item: (item.t, item.student_id))


def within_budget(ranked: list[Ranked], budget_sec: float) -> list[Ranked]:
    chosen, used = [], 0.0
    for item in ranked:
        if used + item.tau > budget_sec:
            break
        chosen.append(item)
        used += item.tau
    return chosen
