"""Gemini とランキングAPIの代わりに使う偽物の部品。評価ハーネス自体を確かめるためのもので、成績の目安にはしない。

関連の確率 r は、主張の言葉とコードの書き方を対応づけた小さな辞書で出す。
"""
import math
import re

from .pipeline import FILE, LINE, Claim, Finding, Node, StagedPipeline

TOP_K = 3  # 各階層で残す件数（企画案 v0.6 の初期値）
ITEM_LIMIT = 80

# 主張の言葉 → それに当たるコードの書き方
LEXICON = {
    "loop": (("ループ", "1つずつ", "順に", "繰り返", "先頭から", "毎回", "全体を"), (r"\bfor\b", r"\bwhile\b")),
    "branch": (("とき", "だけ", "判定", "なら", "かったら", "未満", "以上", "応じて"), (r"\bif\b", r"\belif\b", r"\belse\b")),
    "add": (("足", "合計", "たし", "加え"), (r"\+",)),
    "show": (("表示", "出した", "出して", "出力"), (r"\bprint\(",)),
    "sort": (("並べ替", "並び", "ソート"), (r"\bsort\(", r"\bsorted\(")),
    "compare": (("比べ", "比較", "大きい", "小さい", "最大", "最小"), (r"[<>]=?", r"==")),
    "stop": (("抜け", "終わる", "やめ", "止め"), (r"\bbreak\b",)),
    "function": (("関数", "まとめ"), (r"\bdef\b",)),
    "return": (("返す", "返し"), (r"\breturn\b",)),
    "divide": (("割", "わる", "余り"), (r"%", r"//", r"/")),
    "list": (("リスト", "集め", "追加", "保存"), (r"\[", r"\.append\(")),
    "dict": (("辞書",), (r"\{", r"\.get\(")),
    "init": (("初期値", "最初の値", "仮の", "0から"), (r"\[0\]", r"=\s*0\b")),
    "string": (("文字列", "文字"), (r"[\"']", r"\bstr\(")),
    "reverse": (("スライス", "逆順", "逆に"), (r"\[::-1\]",)),
    "multiply": (("掛け",), (r"\*",)),
    "swap": (("入れかえ", "入れ替え", "交換"), (r"\w+,\s*\w+\s*=\s*\w+,\s*\w+",)),
    "comprehension": (("内包",), (r"\[\w+ for ",)),
}


def concepts_of(text: str) -> set[str]:
    return {name for name, (words, _) in LEXICON.items() if any(word in text for word in words)}


def relevance(concepts: set[str], code: str) -> float:
    """主張の言葉のうち、コードに書き方が見つかる割合を確率らしい値にする。"""
    if not concepts:
        return 0.5
    matched = sum(1 for name in concepts if any(re.search(pattern, code) for pattern in LEXICON[name][1]))
    return 0.2 + 0.8 * math.sqrt(matched / len(concepts))


def _children(nodes: list[Node], parent: str) -> list[Node]:
    return [node for node in nodes if node.parent == parent]


def _top(nodes: list[Node], concepts: set[str]) -> list[tuple[Node, float]]:
    scored = [(node, relevance(concepts, node.text)) for node in nodes]
    return sorted(scored, key=lambda pair: (-pair[1], pair[0].start))[:TOP_K]


class SentenceDecomposer:
    """「。」と改行で区切った文を、そのまま1つの主張にする。"""

    def decompose(self, explanation: str, code: str) -> list[Claim]:
        parts = [part.strip() for part in re.split(r"[。\n]", explanation)]
        return [Claim(f"p{number}", part) for number, part in enumerate((p for p in parts if p), start=1)]


class LexiconFinder:
    """ファイル → 最上位の文 → 行の順に、上位 k 件だけを下の階層へたどる。"""

    def find(self, claim: Claim, nodes: list[Node]) -> Finding:
        concepts = concepts_of(claim.text)
        root = next(node for node in nodes if node.level == FILE)
        r_root = relevance(concepts, root.text)
        best: tuple[float, int, Finding] | None = None
        for block, r_block in _top(_children(nodes, root.id), concepts):
            for line, r_line in _top(_children(nodes, block.id), concepts):
                path = ((root.id, r_root), (block.id, r_block), (line.id, r_line))
                score = math.prod(r for _, r in path)
                if best is None or (score, -line.start) > (best[0], best[1]):
                    best = (score, -line.start, Finding(claim.id, line.id, path))
        return best[2] if best else Finding(claim.id, None)


class FlatFinder:
    """階層をたどらず、全部の行から1回で選ぶ素の検索。比べる相手として使う。"""

    def find(self, claim: Claim, nodes: list[Node]) -> Finding:
        lines = [node for node in nodes if node.level == LINE]
        if not lines:
            return Finding(claim.id, None)
        line, r = _top(lines, concepts_of(claim.text))[0]
        return Finding(claim.id, line.id, ((line.id, r),))


class TemplateWriter:
    def write(self, claim: Claim, node: Node) -> str:
        head = f"{node.start}行目：「"
        tail = "」をどう書いたか説明してもらう"
        room = ITEM_LIMIT - len(head) - len(tail)
        text = claim.text if len(claim.text) <= room else claim.text[: room - 1] + "…"
        return head + text + tail


def lexicon_pipeline() -> StagedPipeline:
    return StagedPipeline("fake-hierarchy", SentenceDecomposer(), LexiconFinder(), TemplateWriter())


def flat_pipeline() -> StagedPipeline:
    return StagedPipeline("fake-flat", SentenceDecomposer(), FlatFinder(), TemplateWriter())


def probing_pipeline() -> StagedPipeline:
    """偽物の根拠探しに、実行ハーネスでの確かめを足したもの。合成コードを手元で実際に動かす。

    APP_ENV=local と ALLOW_LOCAL_SANDBOX=1 のときだけ動く（qgen.sandbox.LocalDevSandbox）。
    """
    from qgen.probes import PatternProbePlanner
    from qgen.sandbox import LocalDevSandbox

    from .behavior import ProbingFinder

    finder = ProbingFinder(LexiconFinder(), PatternProbePlanner(), LocalDevSandbox())
    return StagedPipeline("fake-hierarchy+probe", SentenceDecomposer(), finder, TemplateWriter())

