"""生徒ごとの記録から「本人の説明を聞きたい行」を選ぶ。AIは使わない。

AIを使ったかどうかは判定しない。根拠はどれも機械的に確かめられる事実だけにする。
- 誤答した問いが、その行を指している
- その生徒のこれまでの提出では使っていなかった書き方がある
- このクラスでほかにほとんど使われていない書き方がある
最後の2つは、問いで確かめていない行でも、両方そろったときだけ挙げる。
"""
import ast
from collections import Counter

MAX_SPOTS = 3
MAX_UNASKED = 1
MAX_CODE_CHARS = 120
# クラスがこれより小さいと「ほかに使った人が少ない」に意味がない
MIN_CLASS_FOR_RARE = 3
# 生徒の記録に残す課題の数。古いものから消す
MAX_ENTRIES = 30

BUILTIN_CALLS = {
    "len", "range", "sum", "max", "min", "sorted", "reversed", "enumerate", "zip", "map", "filter",
    "abs", "round", "input", "int", "float", "str", "list", "dict", "set", "tuple", "any", "all",
}
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _label(node: ast.AST) -> str | None:
    """書き方の名前。代入や print のように、どの生徒も使うものは挙げない。"""
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return "`for` 文"
    if isinstance(node, ast.While):
        return "`while` 文"
    if isinstance(node, ast.If):
        return "`if` 文"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "関数の定義（`def`）"
    if isinstance(node, ast.Return):
        return "`return`"
    if isinstance(node, ast.Lambda):
        return "`lambda` 式"
    if isinstance(node, COMPREHENSIONS):
        return "内包表記"
    if isinstance(node, ast.IfExp):
        return "条件式（`a if 条件 else b`）"
    if isinstance(node, ast.AugAssign):
        return "`+=` などの累算代入"
    if isinstance(node, ast.Subscript):
        return "スライス" if isinstance(node.slice, ast.Slice) else "添字（`[ ]`）"
    if isinstance(node, ast.Dict):
        return "辞書"
    if isinstance(node, ast.List) and isinstance(node.ctx, ast.Load):
        return "リスト"
    if isinstance(node, ast.JoinedStr):
        return "f文字列"
    if isinstance(node, ast.Try):
        return "`try` 文"
    if isinstance(node, ast.Break):
        return "`break`"
    if isinstance(node, ast.Continue):
        return "`continue`"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "`import`"
    if isinstance(node, ast.Global):
        return "`global`"
    if isinstance(node, ast.BoolOp):
        return "`and` / `or`"
    if isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        return "`in` 演算子"
    if isinstance(node, ast.Assign) and any(isinstance(target, (ast.Tuple, ast.List)) for target in node.targets):
        return "まとめて代入"
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in BUILTIN_CALLS:
            return f"`{node.func.id}()`"
        if isinstance(node.func, ast.Attribute):
            return f"`.{node.func.attr}()`"
    return None


def constructs_by_line(code: str) -> dict[int, list[str]]:
    """行番号 -> その行で使っている書き方。文法エラーなら空にする。"""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return {}
    found: dict[int, list[str]] = {}
    for node in ast.walk(tree):
        label = _label(node)
        line = getattr(node, "lineno", None)
        if label and line:
            labels = found.setdefault(line, [])
            if label not in labels:
                labels.append(label)
    return {line: found[line] for line in sorted(found)}


def constructs_in(code: str) -> list[str]:
    return sorted({label for labels in constructs_by_line(code).values() for label in labels})


def class_usage(codes: list[str]) -> Counter:
    """書き方ごとに、使った生徒の人数を数える。"""
    usage: Counter = Counter()
    for code in codes:
        usage.update(constructs_in(code))
    return usage


def rare_limit(class_size: int) -> int:
    """この人数以下しか使っていなければ「ほかにほとんど使われていない」とする。"""
    return max(1, class_size // 5)


def find_spots(
    code: str,
    items: list[dict],
    seen: set[str],
    has_history: bool,
    usage: Counter,
    class_size: int,
) -> list[dict]:
    """本人の説明を聞きたい行を、根拠の強い順に MAX_SPOTS 個まで選ぶ。

    items は採点結果で、それぞれ type, stem, correct, line（行を指せない問いは None）を持つ。
    """
    by_line = constructs_by_line(code)
    lines = code.splitlines()
    explained = {item["line"] for item in items if item["correct"] and item.get("line")}
    unexplained: dict[int, list[dict]] = {}
    for item in items:
        if not item["correct"] and item.get("line"):
            unexplained.setdefault(item["line"], []).append(item)
    limit = rare_limit(class_size)
    spots = []
    for line in sorted(set(unexplained) | set(by_line)):
        labels = by_line.get(line, [])
        new = [label for label in labels if has_history and label not in seen]
        rare = [label for label in labels if class_size >= MIN_CLASS_FOR_RARE and usage[label] <= limit]
        missed = unexplained.get(line, [])
        # 問いで確かめていない行は、初めての書き方で、しかもクラスで少ないときだけ挙げる
        if not missed and (line in explained or not (new and rare)):
            continue
        spots.append(
            {
                "line": line,
                "code": lines[line - 1].strip()[:MAX_CODE_CHARS] if 0 < line <= len(lines) else "",
                "constructs": labels,
                "new": new,
                "rare": rare,
                "unexplained": [item["stem"] for item in missed],
                "kinds": sorted({item["type"] for item in missed}),
                "score": spot_score(len(missed), bool(new), bool(rare)),
            }
        )
    spots.sort(key=lambda spot: (-spot["score"], not spot["unexplained"], spot["line"]))
    # 問いで確かめていない行は1つまでにする。同じ書き方（def と return など）で枠が埋まり、
    # 誤答した行が押し出されないようにする
    unasked = [spot for spot in spots if not spot["unexplained"]][:MAX_UNASKED]
    chosen = [spot for spot in spots if spot["unexplained"] or spot in unasked][:MAX_SPOTS]
    output = [item for item in items if not item["correct"] and not item.get("line")]
    if output and len(chosen) < MAX_SPOTS:
        # 出力の予測は行を指せないので、プログラム全体の流れとして最後に置く
        chosen.append(
            {
                "line": None, "code": "", "constructs": [], "new": [], "rare": [],
                "unexplained": [item["stem"] for item in output], "kinds": sorted({item["type"] for item in output}),
                "score": spot_score(len(output), False, False),
            }
        )
    return chosen


def spot_score(missed: int, new: bool, rare: bool) -> int:
    """根拠の強さ。誤答は1問で2、増えるごとに1。初めての書き方と、クラスで少ない書き方は1ずつ。
    両方そろうと、本人に聞かないとわからない度合いが高いので、さらに1を足す（誤答1問より上に来る）。"""
    return (missed + 1 if missed else 0) + int(new) + int(rare) + int(new and rare)


def history_for_ai(entries: list[dict], limit: int = 5) -> list[dict]:
    """AIに渡すこれまでの記録。課題名、正答数、説明を聞いた書き方、教員の処置だけにする。"""
    recent = sorted(entries, key=lambda entry: entry.get("closed_at", 0))[-limit:]
    return [
        {
            "課題": entry.get("title", ""),
            "正答": f"{entry.get('score', 0)}/{entry.get('total', 0)}",
            "説明を聞いた書き方": sorted({label for spot in entry.get("spots", []) for label in spot.get("constructs", [])}),
            "誤答した問いの種類": entry.get("wrong_types", []),
            "教員の記録": (entry.get("action") or {}).get("action", ""),
        }
        for entry in recent
    ]


def recurring_constructs(entries: list[dict], spots: list[dict]) -> list[str]:
    """前の課題でも、説明を聞いた行にあった書き方。続けて難しいところを示す。"""
    before = {label for entry in entries for spot in entry.get("spots", []) if spot.get("unexplained") for label in spot.get("constructs", [])}
    now = {label for spot in spots if spot["unexplained"] for label in spot["constructs"]}
    return sorted(before & now)
