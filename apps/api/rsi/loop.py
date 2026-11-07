"""改善のループ。

1. 今の版を dev で測る
2. パレート上位の候補から親を選び、その失敗例を改善役に渡して書き直し案をもらう
3. 機械的な検査を通った案だけを dev で測り、親より良ければ候補に残す。
   Gemini の出力は毎回変わるので、repeats 回測った平均で比べ、今の版を測ったときの点数の幅（ぶれ）より大きく良くなったときだけ残す
4. 最後に一番よい候補を heldout で1回だけ測り、今の版より下がっていなければ「推薦」にする

AI の呼び出しが失敗して規則の決め方に戻った回は、点数に混ぜない。その候補は「測れなかった」として残し、
ループもそこで止める（上限やネットワークの問題は、続けても直らないことが多い）。

heldout の失敗例は改善役に渡さない。推薦しても本番の版は変えない（変えるのは人）。
"""
import random
from dataclasses import dataclass, field

from evalh.cases import Case
from evalh.runner import EvalConfig, evaluate

from . import checks, objective
from .proposer import FAILURE_SAMPLE, Proposer
from .targets import Target

RECOMMENDED, NO_IMPROVEMENT, REJECTED_BY_HELDOUT = "recommended", "no_improvement", "rejected_by_heldout"
NOT_MEASURED = "not_measured"


class MeasurementError(RuntimeError):
    """AI の呼び出しが失敗して、指示文の良し悪しを測れなかった。"""


@dataclass
class Candidate:
    id: str
    parent: str | None
    prompt: str
    status: str  # baseline / accepted / not_better / rejected / unmeasured
    rationale: str = ""
    reasons: list[str] = field(default_factory=list)
    report: dict | None = None
    notes: list[dict] = field(default_factory=list)

    @property
    def score(self) -> float | None:
        return objective.score(self.report) if self.report else None


@dataclass
class RunResult:
    target: str
    candidates: list[Candidate]
    best: str
    decision: str
    heldout: dict = field(default_factory=dict)  # 候補のid → heldout での点数
    noise: float = 0.0  # 今の版を何回か測ったときの点数の幅

    def candidate(self, candidate_id: str) -> Candidate:
        return next(c for c in self.candidates if c.id == candidate_id)


# 点数（と守るべき決まり）に効く失敗だけを改善役に見せる。根拠の場所の違いなどは点数に入らない
SCORED_FAILURES = {"missed_gap", "false_alarm", "guardrail"}


def _failures_for_proposer(report: dict, rng: random.Random, target: Target | None = None, notes: list[dict] = ()) -> list[dict]:
    useful = [f for f in report["failures"] if f["kind"] in SCORED_FAILURES and (target is None or target.fixable(f, list(notes)))]
    rng.shuffle(useful)
    return useful[:FAILURE_SAMPLE]


def _choose_parent(pool: dict[str, Candidate], rng: random.Random) -> Candidate:
    counts = objective.frontier({key: c.report for key, c in pool.items()})
    keys = sorted(counts)
    return pool[rng.choices(keys, weights=[counts[k] for k in keys])[0]]


def optimize(
    target: Target,
    dev: list[Case],
    heldout: list[Case],
    proposer: Proposer,
    iterations: int = 5,
    repeats: int = 1,
    config: EvalConfig = EvalConfig(),
    workers: int = 1,
    seed: str = "mushitori-rsi",
    log=lambda message: None,
) -> RunResult:
    if {case.split for case in dev} != {"dev"} or {case.split for case in heldout} != {"heldout"}:
        raise ValueError("dev と heldout を取り違えています")
    rng = random.Random(seed)
    secrets = checks.secrets_of(dev + heldout)

    if repeats < 1:
        raise ValueError("repeats は1以上にしてください")

    def measure(prompt: str, cases: list[Case] = dev) -> tuple[dict, list[dict]]:
        reports, notes = [], []
        for _ in range(repeats):
            reports.append(evaluate(target.build(prompt), cases, config, workers))
            if target.api_errors():
                raise MeasurementError(f"AI の呼び出しが {target.api_errors()} 回失敗したので測れませんでした")
            notes += target.notes()
        return objective.merge(reports), notes

    report, notes = measure(target.initial)  # 今の版を測れなければ、何も比べられないので止める
    base = Candidate("c000", None, target.initial, "baseline", report=report, notes=notes)
    candidates, pool = [base], {base.id: base}
    noise = objective.spread(report)  # 同じ指示文でもこれだけは動く。これ以下の差は改善とみなさない
    log(f"c000（今の版）: {base.score:.3f}" + (f"（{repeats}回の幅 {noise:.3f}）" if repeats > 1 else ""))

    for index in range(1, iterations + 1):
        parent = _choose_parent(pool, rng)
        candidate_id = f"c{index:03d}"
        try:
            proposal = proposer.propose(target.name, parent.prompt, _failures_for_proposer(parent.report, rng, target, parent.notes), parent.notes)
        except Exception as error:  # 改善役が止まっても、ループは記録を残して続ける
            candidates.append(Candidate(candidate_id, parent.id, "", "rejected", reasons=[f"改善役が失敗しました: {error}"]))
            log(f"{candidate_id}: 改善役が失敗")
            continue
        reasons = checks.problems(proposal.prompt, target.initial, secrets)
        if proposal.prompt.strip() == parent.prompt.strip():
            reasons.append("親と同じ指示文です")
        if reasons:
            candidates.append(Candidate(candidate_id, parent.id, proposal.prompt, "rejected", proposal.rationale, reasons))
            log(f"{candidate_id}: 検査で却下（{reasons[0]}）")
            continue
        try:
            report, notes = measure(proposal.prompt)
        except MeasurementError as error:
            candidates.append(Candidate(candidate_id, parent.id, proposal.prompt, "unmeasured", proposal.rationale, [str(error)]))
            log(f"{candidate_id}: {error}。ループを止めます")
            break
        child = Candidate(candidate_id, parent.id, proposal.prompt, "not_better", proposal.rationale, report=report, notes=notes)
        if not objective.hard_ok(report):
            child.status, child.reasons = "rejected", ["確認事項の決まりに反しました"]
        elif child.score > parent.score + noise or (
            noise == 0 and child.score == parent.score and objective.better_on_some_case(report, parent.report)
        ):
            child.status = "accepted"
            pool[child.id] = child
        elif child.score > parent.score:
            child.reasons = [f"親より {child.score - parent.score:.3f} 高いが、ぶれ（{noise:.3f}）の範囲です"]
        candidates.append(child)
        log(f"{candidate_id}（親 {parent.id}）: {child.score:.3f} {child.status}")

    best = max(pool.values(), key=lambda c: (c.score, objective.tie_break(c.report), -candidates.index(c)))
    if best is base:
        return RunResult(target.name, candidates, best.id, NO_IMPROVEMENT, noise=noise)
    try:
        held = {c.id: measure(c.prompt, heldout)[0] for c in (base, best)}
    except MeasurementError as error:
        log(f"heldout: {error}")
        return RunResult(target.name, candidates, best.id, NOT_MEASURED, noise=noise)
    scores = {key: objective.score(report) for key, report in held.items()}
    passed = objective.hard_ok(held[best.id]) and scores[best.id] >= scores[base.id]
    log(f"heldout: 今の版 {scores[base.id]:.3f} → {best.id} {scores[best.id]:.3f}")
    return RunResult(target.name, candidates, best.id, RECOMMENDED if passed else REJECTED_BY_HELDOUT, scores, noise)
