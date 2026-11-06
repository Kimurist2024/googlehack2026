"""評価ハーネスが受け取る流れの形。チームの本物の部品も、この形に合わせればそのまま測れる。

根拠の強さ s は経路上の関連の確率 r の積で、根拠が足りない確率は p = 1 - s（企画案 v0.6）。
s は部品に申告させず、返された経路から計算する。
"""
import ast
import math
from dataclasses import dataclass, field
from typing import Protocol

FILE, BLOCK, LINE = "file", "block", "line"


@dataclass(frozen=True)
class Node:
    """根拠を探す階層の節。ファイル → 最上位の文（関数など）→ 行。"""

    id: str
    level: str
    parent: str | None
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class CaseInput:
    """流れに渡す提出物。正解は含めない。"""

    case_id: str
    code: str
    explanation: str
    goal: str


@dataclass(frozen=True)
class Claim:
    id: str
    text: str


@dataclass(frozen=True)
class Finding:
    """主張ごとの根拠探しの結果。path は上の階層から順に (節のid, r)。"""

    claim_id: str
    node_id: str | None
    path: tuple[tuple[str, float], ...] = ()

    @property
    def s(self) -> float:
        if not self.path or self.node_id is None:
            return 0.0
        return math.prod(r for _, r in self.path)

    @property
    def p(self) -> float:
        return 1.0 - self.s


@dataclass(frozen=True)
class CheckItem:
    """教員に見せる確認事項の文面。根拠の場所と確率は Finding から取る。"""

    claim_id: str
    text: str


@dataclass
class PipelineResult:
    nodes: list[Node]
    claims: list[Claim]
    findings: list[Finding]
    items: list[CheckItem] = field(default_factory=list)


class Pipeline(Protocol):
    name: str

    def run(self, case: CaseInput) -> PipelineResult: ...


class Decomposer(Protocol):
    def decompose(self, explanation: str, code: str) -> list[Claim]: ...


class EvidenceFinder(Protocol):
    def find(self, claim: Claim, nodes: list[Node]) -> Finding: ...


class ItemWriter(Protocol):
    def write(self, claim: Claim, node: Node) -> str: ...


def code_nodes(source: str) -> list[Node]:
    """コードを実行せずに、構文だけから根拠の階層を作る。"""
    lines = source.splitlines()
    nodes = [Node("file", FILE, None, 1, max(1, len(lines)), source)]
    try:
        spans = [(stmt.lineno, stmt.end_lineno or stmt.lineno) for stmt in ast.parse(source).body]
    except SyntaxError:
        spans = [(1, max(1, len(lines)))] if lines else []
    for start, end in spans:
        block_id = f"block:{start}-{end}"
        nodes.append(Node(block_id, BLOCK, "file", start, end, "\n".join(lines[start - 1 : end])))
        for number in range(start, end + 1):
            text = lines[number - 1]
            if text.strip():
                nodes.append(Node(f"line:{number}", LINE, block_id, number, number, text))
    return nodes


class StagedPipeline:
    """3つの部品をつないだ流れ。どれか1つだけ本物に差し替えて測れる。"""

    def __init__(self, name: str, decomposer: Decomposer, finder: EvidenceFinder, writer: ItemWriter) -> None:
        self.name = name
        self._decomposer = decomposer
        self._finder = finder
        self._writer = writer

    def run(self, case: CaseInput) -> PipelineResult:
        nodes = code_nodes(case.code)
        by_id = {node.id: node for node in nodes}
        claims = self._decomposer.decompose(case.explanation, case.code)
        findings, items = [], []
        for claim in claims:
            finding = self._finder.find(claim, nodes)
            findings.append(finding)
            # 根拠の場所を示せない確認事項は出さない（企画案 v0.6 の安全性）
            if finding.node_id in by_id:
                items.append(CheckItem(claim.id, self._writer.write(claim, by_id[finding.node_id])))
        return PipelineResult(nodes, claims, findings, items)


def check_result(result: PipelineResult) -> None:
    """流れの出力の形が壊れていたら止める。成績ではなく部品の不具合として扱う。"""
    node_ids = {node.id for node in result.nodes}
    claim_ids = [claim.id for claim in result.claims]
    if len(set(claim_ids)) != len(claim_ids):
        raise ValueError("主張の id が重複しています")
    for finding in result.findings:
        if finding.claim_id not in claim_ids:
            raise ValueError(f"根拠探しの結果が知らない主張を指しています: {finding.claim_id}")
        if finding.node_id is not None and finding.node_id not in node_ids:
            raise ValueError(f"根拠探しの結果が知らない節を指しています: {finding.node_id}")
        for node_id, r in finding.path:
            if node_id not in node_ids or not 0.0 <= r <= 1.0:
                raise ValueError(f"経路の節か確率が不正です: {node_id}, {r}")
    for item in result.items:
        if item.claim_id not in claim_ids:
            raise ValueError(f"確認事項が知らない主張を指しています: {item.claim_id}")
