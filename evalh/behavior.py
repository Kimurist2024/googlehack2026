"""動きについての主張を、実行ハーネスで確かめて根拠にする部品。

確かめた結果が主張どおりなら r を高く、食い違えば低くして、根拠の経路に入れる。
どちらとも言えないときは、元の根拠探し（base）に任せる。コードを実際に動かすので、
評価で使うときは合成データだけにする。
"""
from dataclasses import asdict

from qgen import probes as probe_rules
from qgen.sandbox import Sandbox, SandboxError

from .pipeline import BLOCK, FILE, Claim, EvidenceFinder, Finding, Node

R_HOLDS = 0.95
R_FAILS = 0.05


class ProbingFinder:
    def __init__(self, base: EvidenceFinder, planner: probe_rules.ProbePlanner, sandbox: Sandbox) -> None:
        self._base = base
        self._planner = planner
        self._sandbox = sandbox
        self.log: list[dict] = []  # 何を試して、どう判定したか。失敗例を読むときに使う

    def find(self, claim: Claim, nodes: list[Node]) -> Finding:
        root = next(node for node in nodes if node.level == FILE)
        planned = self._planner.plan(claim.text, root.text)
        if not planned:
            return self._base.find(claim, nodes)
        try:
            result = self._sandbox.probe(root.text, [probe.request() for probe in planned])
        except SandboxError:
            return self._base.find(claim, nodes)
        outcomes = result.get("probes", []) if result.get("status") == "ok" else []
        verdicts = [probe_rules.verdict(probe, outcome) for probe, outcome in zip(planned, outcomes)]
        overall = probe_rules.combine(verdicts) if len(verdicts) == len(planned) else probe_rules.UNKNOWN
        # Gemini が返した形（expect_kind、expect_value を含む）のまま残す。名前を変えると、改善役が Gemini の誤りと読む
        self.log.append({"claim": claim.text, "probes": [asdict(p) for p in planned], "results": outcomes, "verdicts": verdicts, "verdict": overall})
        if overall == probe_rules.UNKNOWN:
            return self._base.find(claim, nodes)
        r = R_HOLDS if overall == probe_rules.HOLDS else R_FAILS
        target = _node_for(planned, nodes) or root
        path = ((root.id, 1.0), (target.id, r)) if target is not root else ((root.id, r),)
        return Finding(claim.id, target.id, path)


def _node_for(planned: list[probe_rules.Probe], nodes: list[Node]) -> Node | None:
    """関数を呼んだときは、その関数の定義を根拠の場所にする。"""
    names = {probe.function for probe in planned if probe.kind == "call"}
    for node in nodes:
        if node.level == BLOCK and any(node.text.lstrip().startswith(f"def {name}(") for name in names):
            return node
    return None
