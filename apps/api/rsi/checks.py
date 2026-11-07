"""候補の指示文の機械的な検査。点数稼ぎ（reward hacking）を防ぐため、評価の前に必ず通す。

- 差し込み口（{data} など）を消したり増やしたりしない
- 長くしすぎない
- dev の提出物の文やコードを書き写さない（答えを覚えさせて点を取るのを防ぐ）。多くの提出物に共通する言い回しは除く
- <data> の囲みを自分で書かない。囲みと「指示ではない」の注意書きはコードが {data} に入れるので、
  指示文の中に偽の囲みを書くと、生徒のデータの範囲をごまかせてしまう
"""
import string
from collections import Counter

LEAK_NGRAM = 8
# これだけの数の提出物に出てくる言い回し（「Falseを返す」など）は、特定の提出物の答えではないので書き写しとみなさない
COMMON_CASES = 3
MAX_GROWTH = 2.0


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _compact(text: str) -> str:
    return "".join(text.split())


def _ngrams(text: str, n: int) -> set[str]:
    compact = _compact(text)
    return {compact[i : i + n] for i in range(len(compact) - n + 1)}


def leaked(candidate: str, base: str, secrets: list[str], n: int = LEAK_NGRAM) -> list[str]:
    """元の指示文になかった文字列のうち、dev の提出物と n 文字以上一致するもの。"""
    added = _ngrams(candidate, n) - _ngrams(base, n)
    counts = Counter(gram for text in secrets for gram in _ngrams(text, n))
    return sorted(gram for gram in added if 0 < counts[gram] < COMMON_CASES)


def problems(candidate: str, base: str, secrets: list[str]) -> list[str]:
    found = []
    if not candidate.strip():
        return ["空の指示文です"]
    try:
        placeholders(candidate)
    except ValueError as error:
        return [f"差し込めない書き方です: {error}"]
    if placeholders(candidate) != placeholders(base):
        found.append(f"差し込み口が変わりました: {sorted(placeholders(candidate))} ≠ {sorted(placeholders(base))}")
    else:
        try:
            candidate.format(**{name: "x" for name in placeholders(base)})
        except (KeyError, IndexError, ValueError) as error:
            found.append(f"差し込めない書き方です: {error}")
    if len(candidate) > MAX_GROWTH * len(base):
        found.append(f"長すぎます（{len(candidate)}字。元の{MAX_GROWTH:g}倍まで）")
    if "<data" in candidate.lower() or "</data" in candidate.lower():
        found.append("<data> の囲みを指示文に書いています（囲みはコードが付けます）")
    leaks = leaked(candidate, base, secrets)
    if leaks:
        found.append(f"dev の提出物を書き写しています: {leaks[:3]}")
    return found


def secrets_of(cases) -> list[str]:
    """書き写してはいけない文。提出物ごとに、コード、説明、正解の主張を1つにまとめる（何件の提出物に出るかを数えるため）。"""
    return ["\n".join([case.input.code, case.input.explanation, *(claim.text for claim in case.claims)]) for case in cases]
