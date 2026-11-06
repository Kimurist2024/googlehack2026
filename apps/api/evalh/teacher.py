"""模擬教員と、処置による確率の校正。

模擬教員は正解ラベルどおりに処置し、noise の割合で間違える。処置にかかった秒数もばらつかせる。
校正は確率の帯ごとに p̃ = (1 + 有用) ÷ (2 + 処置数)、τ は処置にかかった秒数の中央値（企画案 v0.6）。
"""
import random
from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class Disposition:
    key: str
    p: float
    useful: bool  # 「授業で聞く」に当たる。問題なし・AIの誤りは False
    seconds: float


def simulate(rows: list[tuple[str, float, bool]], noise: float, tau_sec: float, rng: random.Random) -> list[Disposition]:
    """rows は (確認事項のキー, p, 本当に理解不足か)。"""
    found = []
    for key, p, is_gap in rows:
        useful = is_gap if rng.random() >= noise else not is_gap
        found.append(Disposition(key, p, useful, tau_sec * rng.uniform(0.5, 1.5)))
    return found


def band_of(p: float, bands: int) -> int:
    return min(int(p * bands), bands - 1)


def band_table(dispositions: list[Disposition], bands: int = 5) -> dict[int, float]:
    table = {}
    for band in range(bands):
        inside = [d for d in dispositions if band_of(d.p, bands) == band]
        if inside:
            table[band] = (1 + sum(d.useful for d in inside)) / (2 + len(inside))
    return table


def calibrated(p: float, table: dict[int, float], bands: int = 5) -> float:
    """処置のない帯は元の p のまま使う。"""
    return table.get(band_of(p, bands), p)


def tau_after(dispositions: list[Disposition], default: float) -> float:
    return float(median(d.seconds for d in dispositions)) if dispositions else default
