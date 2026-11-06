"""デモ用の合成データ。実在の生徒の提出物は使わない。"""

TITLE = "点数の合計（条件つき）"
LEARNING_GOAL = "繰り返しと条件分岐で、変数の値がどう変わるかを追える"
WEIGHTS = {"output": 1.0, "trace": 2.0, "impact": 2.0}

PROGRAMS = {
    "1": """scores = [72, 95, 58, 88, 40]
total = 0
for s in scores:
    if s >= 60:
        total = total + s
print(total)
""",
    "2": """scores = [72, 95, 58, 88, 40]
total = 0
count = 0
for s in scores:
    if s >= 60:
        total += s
        count = count + 1
print(count)
print(total)
""",
    "3": """def passed_total(items, line):
    result = 0
    for value in items:
        if value >= line:
            result = result + value
    return result

print(passed_total([72, 95, 58, 88, 40], 60))
""",
    "4": """scores = [72, 95, 58, 88, 40]
kept = []
i = 0
while i < len(scores):
    if scores[i] > 59:
        kept.append(scores[i])
    i = i + 1
total = 0
for k in kept:
    total = total + k
print(total)
""",
    "5": """scores = [72, 95, 58, 88, 40]
i = 0
total = 0
while i < len(scores):
    total = total + scores[i]
""",
    "6": """scores = [72, 95, 58, 88, 40]
print(scores[10])
""",
}

# これまでの課題の記録（合成）。デモで「蓄積された記録」から質問案を作る流れを見せるために使う
PAST_TITLES = ("合計を求める（第1回）", "最大値を探す（第2回）")
BASIC = ["`for` 文", "`if` 文", "リスト"]


def _spot(line: int, code: str, constructs: list[str], stem: str, question: str) -> dict:
    return {"line": line, "code": code, "constructs": constructs, "new": [], "rare": [], "unexplained": [stem], "question": question}


# 出席番号 -> 第1回と第2回の (正答数, 誤答した問いの種類, 使った書き方, 説明を聞いた行, 教員の記録)
PAST = {
    "1": [
        (2, ["trace"], BASIC, [_spot(5, "total = total + s", [], "変数 `total` が取る値の3番目", "5行目を実行すると、どの値がどう変わりますか。")], "explained"),
        (3, [], BASIC, [], None),
    ],
    "2": [
        (1, ["output", "trace"], BASIC + ["`len()`"], [_spot(3, "for s in scores:", ["`for` 文"], "変数 `s` が取る値の2番目", "3行目の `for` 文で、s にはどの順に値が入りますか。")], "not_explained"),
        (2, ["trace"], BASIC, [_spot(4, "for s in scores:", ["`for` 文"], "変数 `best` が取る値の3番目", "4行目で s が変わるたびに、何が起きますか。")], "explained"),
    ],
    "3": [
        (3, [], BASIC, [], None),
        (2, ["impact"], BASIC, [_spot(4, "if s > best:", ["`if` 文"], "4行目の `>` を `>=` に変えたとき", "4行目の条件を変えると、結果はどう変わりますか。")], "explained"),
    ],
    "4": [
        (2, ["trace"], BASIC + ["`while` 文", "`len()`", "添字（`[ ]`）"], [_spot(4, "while i < len(scores):", ["`while` 文", "`len()`"], "変数 `i` が取る値の4番目", "4行目の条件は、いつまで成り立ちますか。")], "explained"),
        (3, [], BASIC + ["`while` 文", "`len()`", "添字（`[ ]`）"], [], None),
    ],
}


def past_entries(number: str, now: float) -> list[dict]:
    """その生徒の、これまでの課題の記録。1週間ごとに締め切ったことにする。"""
    entries = []
    for index, (score, wrong_types, constructs, spots, action) in enumerate(PAST.get(number, [])):
        entries.append(
            {
                "assignment_id": f"demo-past-{index + 1}",
                "title": PAST_TITLES[index],
                "closed_at": now - (len(PAST_TITLES) - index) * 7 * 24 * 3600,
                "score": score,
                "total": 3,
                "wrong_types": wrong_types,
                "constructs": sorted(constructs),
                "spots": spots,
                "action": {"action": action, "reason": ""} if action else None,
            }
        )
    return entries
