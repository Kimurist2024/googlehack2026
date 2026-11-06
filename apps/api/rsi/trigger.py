"""指示文を見直すきっかけ（企画案 v0.6 p.20）。

確認枠で抜き出した n 件のうち h 件で問題が見つかったとき、見逃し率 m̂ = h ÷ n の
95% 下限（ウィルソンの方法）が 10% を超えたら、抽出率を2倍にして指示文を見直す。
"""
import math

Z95 = 1.959964
LIMIT = 0.10


def wilson_lower(found: int, sampled: int, z: float = Z95) -> float:
    if sampled <= 0:
        return 0.0
    rate = found / sampled
    centre = rate + z * z / (2 * sampled)
    margin = z * math.sqrt(rate * (1 - rate) / sampled + z * z / (4 * sampled * sampled))
    return max(0.0, (centre - margin) / (1 + z * z / sampled))


def needs_review(found: int, sampled: int, limit: float = LIMIT) -> bool:
    return wilson_lower(found, sampled) > limit
