"""成績を人が読む表にする。複数の流れを横に並べて比べられる。"""

FAILURE_LIMIT = 30
KIND_LABELS = {
    "missed_gap": "理解不足を見逃した",
    "false_alarm": "正しい主張を確かめる側に出した",
    "wrong_evidence": "根拠の場所が違う",
    "missed_claim": "主張を取り出せなかった",
    "extra_claim": "正解にない主張を出した",
    "guardrail": "決まりに反した",
}


def _num(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _row(label: str, values: list) -> str:
    return f"| {label} | " + " | ".join(values) + " |"


def to_markdown(reports: list[dict]) -> str:
    first = reports[0]
    names = [report["pipeline"] for report in reports]
    lines = [
        f"# 評価ハーネスの結果（{', '.join(first['splits'])}、{first['cases']}件）",
        "",
        "| 指標 | " + " | ".join(names) + " |",
        "| --- | " + " | ".join("---" for _ in names) + " |",
        _row("主張の再現率", [_num(r["decomposition"]["recall"]) for r in reports]),
        _row("主張の適合率", [_num(r["decomposition"]["precision"]) for r in reports]),
        _row("根拠が1位に来る割合", [_num(r["retrieval"]["hit_at_1"]) for r in reports]),
        _row("ブライアスコア（低いほど良い）", [_num(r["calibration"]["brier"]) for r in reports]),
        _row("校正の誤差 ECE（低いほど良い）", [_num(r["calibration"]["ece"]) for r in reports]),
    ]
    for index, row in enumerate(first["budget"]["ranked"]):
        budget = int(row["budget_sec"])
        lines.append(_row(f"{budget}秒で拾える理解不足", [_num(r["budget"]["ranked"][index]["recall"]) for r in reports]))
        lines.append(_row(f"{budget}秒・出席番号順に丸ごと", [_num(r["budget"]["whole_review"][index]["recall"]) for r in reports]))
    lines += [
        _row("処置で校正する前のブライア", [_num((r["feedback"] or {}).get("brier_before")) for r in reports]),
        _row("処置で校正した後のブライア", [_num((r["feedback"] or {}).get("brier_after")) for r in reports]),
        _row("決まりに反した確認事項", [f"{r['guardrails']['violations']} / {r['guardrails']['items']}" for r in reports]),
        "",
        f"理解不足は全部で {first['budget']['gaps']} 件。偽物の部品（fake-）の数字は配線の確認用で、成績の目安ではない。",
    ]
    for report in reports:
        lines += ["", f"## 失敗例：{report['pipeline']}（{len(report['failures'])}件）", ""]
        counts = {}
        for failure in report["failures"]:
            counts[failure["kind"]] = counts.get(failure["kind"], 0) + 1
        lines.append("、".join(f"{KIND_LABELS.get(kind, kind)} {count}件" for kind, count in sorted(counts.items())) or "なし")
        lines.append("")
        for failure in report["failures"][:FAILURE_LIMIT]:
            detail = failure.get("gold_claim") or failure.get("pred_claim") or failure.get("text", "")
            extra = f"（p={failure['p']:.2f}）" if "p" in failure else ""
            lines.append(f"- {failure['case_id']} {KIND_LABELS.get(failure['kind'], failure['kind'])}：{detail}{extra}")
        if len(report["failures"]) > FAILURE_LIMIT:
            lines.append(f"- ほか {len(report['failures']) - FAILURE_LIMIT} 件")
    return "\n".join(lines) + "\n"
