"""成績の計算。AIは使わず、同じ入力なら同じ値になる。"""
from dataclasses import dataclass

from qgen.ai import JUDGING_WORDS, LINK_PATTERN

ITEM_LIMIT = 80


def bigrams(text: str) -> set[str]:
    compact = "".join(text.split())
    return {compact[i : i + 2] for i in range(len(compact) - 1)} or {compact}


def dice(a: str, b: str) -> float:
    x, y = bigrams(a), bigrams(b)
    return 2 * len(x & y) / (len(x) + len(y)) if x and y else 0.0


def match_claims(gold: list[tuple[str, str]], pred: list[tuple[str, str]], threshold: float) -> dict[str, str]:
    """(id, 文) の組どうしを、似ている順に1対1で結ぶ。返り値は 正解のid → 流れのid。"""
    pairs = sorted(
        ((dice(g_text, p_text), g_id, p_id) for g_id, g_text in gold for p_id, p_text in pred),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    matched: dict[str, str] = {}
    used: set[str] = set()
    for score, g_id, p_id in pairs:
        if score < threshold:
            break
        if g_id not in matched and p_id not in used:
            matched[g_id] = p_id
            used.add(p_id)
    return matched


def prf(matched: int, gold: int, pred: int) -> dict:
    precision = matched / pred if pred else 0.0
    recall = matched / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "gold": gold, "pred": pred, "matched": matched}


def brier(pairs: list[tuple[float, int]]) -> float | None:
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None


def calibration(pairs: list[tuple[float, int]], bins: int = 5) -> dict:
    """予測した確率 p と、実際に根拠が足りなかったか y の一致。ECE は帯ごとのずれの重みつき平均。"""
    rows, ece = [], 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        inside = [(p, y) for p, y in pairs if low <= p < high or (index == bins - 1 and p == 1.0)]
        if not inside:
            continue
        mean_p = sum(p for p, _ in inside) / len(inside)
        rate = sum(y for _, y in inside) / len(inside)
        ece += len(inside) / len(pairs) * abs(mean_p - rate)
        rows.append({"low": low, "high": high, "n": len(inside), "mean_p": mean_p, "gap_rate": rate})
    return {"n": len(pairs), "brier": brier(pairs), "ece": ece if pairs else None, "bins": rows}


@dataclass(frozen=True)
class Violation:
    claim_id: str
    kind: str  # too_long / no_evidence / judging_words
    text: str


def guardrail_violations(claim_id: str, text: str, has_evidence: bool) -> list[Violation]:
    """企画案の決まり：80字以内、根拠リンク必須、生徒を評価する言葉を使わない。URL も書かない（qgen/ai.py と同じ）。"""
    found = []
    if len(text) > ITEM_LIMIT:
        found.append(Violation(claim_id, "too_long", text))
    if not has_evidence:
        found.append(Violation(claim_id, "no_evidence", text))
    if any(word in text for word in JUDGING_WORDS):
        found.append(Violation(claim_id, "judging_words", text))
    if LINK_PATTERN.search(text):
        found.append(Violation(claim_id, "link", text))
    return found
