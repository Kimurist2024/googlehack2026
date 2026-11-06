"""候補の良し悪しの決め方。点数は評価ハーネスの結果だけから計算し、AIには付けさせない。"""


def merge(reports: list[dict]) -> dict:
    """同じ指示文を何回か測った結果をまとめる。Gemini の出力は毎回少し変わるので、平均で比べる。

    per_case とブライアスコアは平均、決まりへの違反は一番多かった回、失敗例は全部の回のものを重複なしで残す。
    """
    if len(reports) == 1:
        return reports[0]
    first = reports[0]
    cases = first["per_case"]
    briers = [r["calibration"]["brier"] for r in reports if r["calibration"]["brier"] is not None]
    seen, failures = set(), []
    for report in reports:
        for failure in report["failures"]:
            key = repr(sorted(failure.items()))
            if key not in seen:
                seen.add(key)
                failures.append(failure)
    return first | {
        "per_case": {case: sum(r["per_case"].get(case, 0.0) for r in reports) / len(reports) for case in cases},
        "calibration": first["calibration"] | {"brier": sum(briers) / len(briers) if briers else None},
        "guardrails": first["guardrails"] | {"violations": max(r["guardrails"]["violations"] for r in reports)},
        "failures": failures,
        "repeats": [score(r) for r in reports],
    }


def spread(report: dict) -> float:
    """何回か測ったときの点数の幅（最大 − 最小）。1回だけなら 0。"""
    runs = report.get("repeats") or [score(report)]
    return max(runs) - min(runs)


def score(report: dict) -> float:
    """提出物ごとの「正しく扱えた主張の割合」の平均。どの提出物も同じ重みで数える。"""
    per_case = report["per_case"]
    return sum(per_case.values()) / len(per_case) if per_case else 0.0


def hard_ok(report: dict) -> bool:
    """これを満たさない候補は、点数がいくら高くても使わない。"""
    return report["guardrails"]["violations"] == 0


def tie_break(report: dict) -> float:
    """点数が同じときは、確率の当たりがよい（ブライアスコアが低い）方を上にする。"""
    brier = report["calibration"]["brier"]
    return -brier if brier is not None else float("-inf")


def better_on_some_case(child: dict, parent: dict) -> bool:
    return any(child["per_case"].get(case, 0.0) > value for case, value in parent["per_case"].items())


def frontier(reports: dict[str, dict]) -> dict[str, int]:
    """提出物ごとに一番よい候補を数える（GEPA のパレート選択）。1件でも一番なら親になれる。"""
    counts = {key: 0 for key in reports}
    cases = {case for report in reports.values() for case in report["per_case"]}
    for case in sorted(cases):
        best = max(report["per_case"].get(case, 0.0) for report in reports.values())
        for key, report in reports.items():
            if report["per_case"].get(case, 0.0) == best:
                counts[key] += 1
    return {key: count for key, count in counts.items() if count}
