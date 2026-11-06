"""模擬提出物に流れをかけて、成績と失敗例をまとめる。

失敗例は自動改善（RSI）が指示文を直す手がかりに使う。正解の文は失敗例に含めるが、
heldout の提出物はここに渡さないこと（cases.load_cases で split を分ける）。
"""
import random
from dataclasses import asdict, dataclass, field

from . import budget, metrics, teacher
from .cases import Case
from .pipeline import LINE, Pipeline, check_result


@dataclass(frozen=True)
class EvalConfig:
    match_threshold: float = 0.5  # 主張どうしを同じとみなす文の似かた
    flag_threshold: float = 0.5  # p がこれ以上なら「確かめる」と出したとみなす
    tau_sec: float = 30.0
    weight: float = 1.0
    budgets: tuple[float, ...] = (60, 120, 300, 600)
    audit_sec: float = 0.0  # 確認枠に回す時間
    per_submission_sec: float = 150.0  # 丸ごと見るときの1件の秒数（企画案 p.20 の仮定）
    whole_review_find_rate: float = 1.0
    teacher_noise: float = 0.1
    bands: int = 5
    seed: str = "mushitori-eval"


@dataclass
class _Tally:
    gold: int = 0
    pred: int = 0
    matched: int = 0
    evidence_total: int = 0
    evidence_hit: int = 0
    pairs: list = field(default_factory=list)  # (p, y)
    feedback_rows: list = field(default_factory=list)  # (key, p, is_gap)
    budget_items: list = field(default_factory=list)
    gap_keys: set = field(default_factory=set)
    gaps_by_student: dict = field(default_factory=dict)
    items: int = 0
    violations: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    per_case: dict = field(default_factory=dict)  # 提出物ごとの、正しく扱えた主張の割合


def _in_evidence(line: int, evidence: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= line <= end for start, end in evidence)


def _evaluate_case(case: Case, pipeline: Pipeline, config: EvalConfig, tally: _Tally) -> None:
    result = pipeline.run(case.input)
    check_result(result)
    nodes = {node.id: node for node in result.nodes}
    findings = {finding.claim_id: finding for finding in result.findings}
    pred_text = {claim.id: claim.text for claim in result.claims}
    matched = metrics.match_claims(
        [(g.id, g.text) for g in case.claims], [(c.id, c.text) for c in result.claims], config.match_threshold
    )
    gold_of_pred = {pred_id: gold_id for gold_id, pred_id in matched.items()}
    gold = {g.id: g for g in case.claims}

    tally.gold += len(case.claims)
    tally.pred += len(result.claims)
    tally.matched += len(matched)
    tally.gaps_by_student[case.id] = sum(g.is_gap for g in case.claims)

    def fail(kind: str, **detail) -> None:
        tally.failures.append({"case_id": case.id, "kind": kind, **detail})

    handled = 0
    for claim in case.claims:
        pred_id = matched.get(claim.id)
        if pred_id is None:
            fail("missed_claim", gold_claim=claim.text, label=claim.label)
            continue
        finding = findings.get(pred_id)
        p = finding.p if finding else 1.0
        handled += int((p >= config.flag_threshold) == claim.is_gap)
        tally.pairs.append((p, int(claim.is_gap)))
        tally.feedback_rows.append((f"{case.id}/{pred_id}", p, claim.is_gap))
        node = nodes.get(finding.node_id) if finding and finding.node_id else None
        if claim.is_gap and p < config.flag_threshold:
            fail("missed_gap", gold_claim=claim.text, pred_claim=pred_text[pred_id], p=p, node=_where(node))
        if not claim.is_gap and p >= config.flag_threshold:
            fail("false_alarm", gold_claim=claim.text, label=claim.label, pred_claim=pred_text[pred_id], p=p, node=_where(node))
        if claim.evidence:
            tally.evidence_total += 1
            if node is not None and node.level == LINE and _in_evidence(node.start, claim.evidence):
                tally.evidence_hit += 1
            else:
                fail("wrong_evidence", gold_claim=claim.text, expected=[list(r) for r in claim.evidence], node=_where(node))

    tally.per_case[case.id] = handled / len(case.claims) if case.claims else 1.0

    for claim in result.claims:
        if claim.id not in gold_of_pred:
            fail("extra_claim", pred_claim=claim.text)

    for item in result.items:
        finding = findings.get(item.claim_id)
        node = nodes.get(finding.node_id) if finding and finding.node_id else None
        tally.items += 1
        for violation in metrics.guardrail_violations(item.claim_id, item.text, node is not None):
            tally.violations.append({"case_id": case.id, **asdict(violation)})
            fail("guardrail", rule=violation.kind, text=item.text)
        if node is None:
            continue
        key = f"{case.id}/{item.claim_id}"
        tally.budget_items.append(budget.BudgetItem(key, case.id, finding.p, config.weight, config.tau_sec))
        gold_id = gold_of_pred.get(item.claim_id)
        if gold_id is not None and gold[gold_id].is_gap:
            tally.gap_keys.add(key)


def _where(node) -> dict | None:
    return {"id": node.id, "line": node.start, "text": node.text.strip()} if node is not None else None


def _feedback(rows: list[tuple[str, float, bool]], config: EvalConfig) -> dict | None:
    """前半の処置で帯ごとに校正し、後半でブライアスコアが下がるかを見る。"""
    if len(rows) < 4:
        return None
    rng = random.Random(config.seed)
    shuffled = rows[:]
    rng.shuffle(shuffled)
    half = len(shuffled) // 2
    learn, check = shuffled[:half], shuffled[half:]
    dispositions = teacher.simulate(learn, config.teacher_noise, config.tau_sec, rng)
    table = teacher.band_table(dispositions, config.bands)
    before = [(p, int(is_gap)) for _, p, is_gap in check]
    after = [(teacher.calibrated(p, table, config.bands), int(is_gap)) for _, p, is_gap in check]
    return {
        "dispositions": len(dispositions),
        "checked": len(check),
        "brier_before": metrics.brier(before),
        "brier_after": metrics.brier(after),
        "band_table": {str(band): value for band, value in sorted(table.items())},
        "tau_after": teacher.tau_after(dispositions, config.tau_sec),
    }


def evaluate(pipeline: Pipeline, cases: list[Case], config: EvalConfig = EvalConfig()) -> dict:
    tally = _Tally()
    for case in cases:
        _evaluate_case(case, pipeline, config, tally)
    total_gaps = sum(tally.gaps_by_student.values())
    budgets = list(config.budgets)
    return {
        "pipeline": pipeline.name,
        "cases": len(cases),
        "splits": sorted({case.split for case in cases}),
        "config": asdict(config),
        "decomposition": metrics.prf(tally.matched, tally.gold, tally.pred),
        "retrieval": {
            "evaluated": tally.evidence_total,
            "hit_at_1": tally.evidence_hit / tally.evidence_total if tally.evidence_total else None,
        },
        "calibration": metrics.calibration(tally.pairs, config.bands),
        "budget": {
            "gaps": total_gaps,
            "ranked": budget.recall_curve(tally.budget_items, tally.gap_keys, total_gaps, budgets, config.audit_sec),
            "whole_review": budget.whole_review_curve(
                tally.gaps_by_student, total_gaps, budgets, config.per_submission_sec, config.whole_review_find_rate
            ),
        },
        "feedback": _feedback(tally.feedback_rows, config),
        "guardrails": {
            "items": tally.items,
            "violations": len(tally.violations),
            "rate": len(tally.violations) / tally.items if tally.items else 0.0,
            "by_rule": {rule: sum(v["kind"] == rule for v in tally.violations) for rule in ("too_long", "no_evidence", "judging_words")},
        },
        "per_case": tally.per_case,
        "failures": tally.failures,
    }
