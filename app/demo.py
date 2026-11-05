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
