"""実行結果から問いの候補を作る。正解はすべて実行結果から出し、AIには作らせない。"""
import hashlib
import random
from collections import Counter
from dataclasses import asdict, dataclass, field

OUTPUT, TRACE, IMPACT = "output", "trace", "impact"
TYPE_ORDER = (OUTPUT, TRACE, IMPACT)
OPTION_COUNT = 4


@dataclass
class Question:
    id: str
    type: str
    stem: str
    answer: str
    options: list[str] = field(default_factory=list)  # 空なら自由入力
    line: int | None = None
    trace: list[str] = field(default_factory=list)  # 解説に使う実行の記録

    def public(self) -> dict:
        """生徒に渡してよい項目だけを返す。正解と記録は含めない。"""
        return {"id": self.id, "type": self.type, "stem": self.stem, "options": self.options}

    def to_dict(self) -> dict:
        return asdict(self)


def seeded_random(*parts: str) -> random.Random:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _kind(text: str) -> str:
    try:
        float(text)
        return "number"
    except ValueError:
        return "text"


def _printable(value_repr: str) -> str:
    """repr の文字列は引用符を外し、表示と同じ形にそろえる。"""
    if len(value_repr) >= 2 and value_repr[0] == value_repr[-1] and value_repr[0] in "'\"":
        return value_repr[1:-1]
    return value_repr


def _options(answer: str, pool: list[str], rng: random.Random) -> list[str]:
    """正解と同じ種類の誤答候補を選ぶ。3つそろわなければ自由入力にする。"""
    kind = _kind(answer)
    wrong = []
    # 初出順で重複を除く。抽選順を保ち、候補ごとのリスト全探索をなくす。
    for candidate in dict.fromkeys(pool):
        if candidate and candidate != answer and _kind(candidate) == kind:
            wrong.append(candidate)
    if len(wrong) < OPTION_COUNT - 1:
        return []
    options = rng.sample(wrong, OPTION_COUNT - 1) + [answer]
    rng.shuffle(options)
    return options


def _scope_label(scope: str) -> str:
    return f"関数 `{scope}` の中の" if scope else ""


def build_candidates(result: dict, stdin: str, seed: str) -> list[Question]:
    if result.get("status") != "ok":
        return []
    rng = seeded_random(seed)
    answer = last_line(result.get("stdout", ""))
    history = result.get("history", [])
    mutants = [m for m in result.get("mutants", []) if m.get("status") == "ok"]
    mutant_outputs = [last_line(m.get("stdout", "")) for m in mutants]
    seen_values = [_printable(entry["value"]) for entry in history]
    candidates: list[Question] = []

    if answer:
        given = f"入力が `{last_line(stdin)}` のとき、" if stdin.strip() else ""
        candidates.append(
            Question(
                id="output-1",
                type=OUTPUT,
                stem=f"{given}このプログラムが最後に表示する内容は何ですか。",
                answer=answer,
                options=_options(answer, mutant_outputs + seen_values, rng),
            )
        )

    series: dict[tuple[str, str], list[dict]] = {}
    for entry in history:
        series.setdefault((entry["scope"], entry["name"]), []).append(entry)
    usable = [key for key, entries in series.items() if len(entries) >= 3]
    for number, key in enumerate(usable, start=1):
        entries = series[key]
        position = rng.randrange(2, min(len(entries), 6))
        chosen = entries[position]
        values = [_printable(entry["value"]) for entry in entries]
        scope, name = key
        candidates.append(
            Question(
                id=f"trace-{number}",
                type=TRACE,
                stem=f"{_scope_label(scope)}変数 `{name}` が取る値を順に並べたとき、{position + 1}番目の値は何ですか。",
                answer=values[position],
                options=_options(values[position], values + seen_values, rng),
                line=chosen["line"],
                trace=values[: position + 1],
            )
        )

    same_place = Counter((m["line"], m["before"]) for m in mutants)
    for number, mutant in enumerate(mutants, start=1):
        changed = last_line(mutant.get("stdout", ""))
        # 同じ行に同じ記号が2つあると、問いの指す場所があいまいになる
        if not changed or changed == answer or same_place[(mutant["line"], mutant["before"])] > 1:
            continue
        candidates.append(
            Question(
                id=f"impact-{number}",
                type=IMPACT,
                stem=f"{mutant['line']}行目の `{mutant['before']}` を `{mutant['after']}` に変えると、最後に表示される内容は何になりますか。",
                answer=changed,
                options=_options(changed, [answer] + mutant_outputs + seen_values, rng),
                line=mutant["line"],
            )
        )
    return candidates


def default_selection(candidates: list[Question], count: int, seed: str) -> list[Question]:
    """AIが使えないときの既定の選び方。可能なら種類が分かれるように選ぶ。"""
    rng = seeded_random(seed, "selection")
    grouped = {kind: [q for q in candidates if q.type == kind] for kind in TYPE_ORDER}
    for group in grouped.values():
        rng.shuffle(group)
    chosen: list[Question] = []
    while len(chosen) < count and any(grouped.values()):
        for kind in TYPE_ORDER:
            if grouped[kind] and len(chosen) < count:
                chosen.append(grouped[kind].pop())
    return chosen
