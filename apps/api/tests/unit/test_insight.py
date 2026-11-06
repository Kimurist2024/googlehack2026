"""本人の説明を聞きたい行の選び方の試験。AIは使わない。"""
from collections import Counter

from app.insight import (
    MAX_SPOTS, class_usage, constructs_by_line, constructs_in, find_spots, history_for_ai, rare_limit, recurring_constructs, spot_score,
)

CODE = """scores = [72, 95, 58]
kept = [s for s in scores if s >= 60]
total = 0
for k in kept:
    total += k
print(total)
"""


def item(line, correct=False, stem="問い", kind="trace"):
    return {"type": kind, "stem": stem, "correct": correct, "line": line}


def test_constructs_are_found_per_line_and_common_ones_are_left_out():
    found = constructs_by_line(CODE)
    assert found[1] == ["リスト"] and "内包表記" in found[2] and found[4] == ["`for` 文"]
    assert found[5] == ["`+=` などの累算代入"]
    # 代入や print はどの生徒も使うので挙げない
    assert 3 not in found and 6 not in found


def test_broken_code_has_no_constructs():
    assert constructs_by_line("for x in\n") == {} and constructs_in("for x in\n") == []


def test_calls_are_named_and_user_functions_are_not():
    found = constructs_in("def f(x):\n    return len(x)\nitems = []\nitems.append(f(items))\n")
    assert {"関数の定義（`def`）", "`return`", "`len()`", "`.append()`"} <= set(found)
    assert not any("f()" in label for label in found)


def test_usage_counts_each_student_once():
    usage = class_usage([CODE, CODE.replace("total += k", "total = total + k"), "x = 1\n"])
    assert usage["`for` 文"] == 2 and usage["`+=` などの累算代入"] == 1 and usage["リスト"] == 2


def test_rare_limit_grows_with_the_class():
    assert [rare_limit(size) for size in (3, 9, 10, 40)] == [1, 1, 2, 8]


def spots_for(items, seen=frozenset(), has_history=True, usage=None, class_size=6):
    usage = usage if usage is not None else Counter({"リスト": 6, "`for` 文": 6, "`+=` などの累算代入": 6})
    return find_spots(CODE, items, set(seen), has_history, usage, class_size)


def test_unexplained_lines_come_first_with_their_evidence():
    spots = spots_for([item(4), item(5, correct=True), item(None, kind="output", stem="最後の表示")], seen={"`for` 文", "リスト", "`+=` などの累算代入", "内包表記"})
    assert [spot["line"] for spot in spots] == [4, None]
    assert spots[0]["code"] == "for k in kept:" and spots[0]["unexplained"] == ["問い"]
    assert spots[1]["unexplained"] == ["最後の表示"]


def test_a_new_and_rare_line_is_raised_even_without_a_question():
    # 内包表記はこの生徒が初めて使い、クラスでもほかに使った人がいない
    spots = spots_for([item(4, correct=True)], seen={"`for` 文", "リスト", "`+=` などの累算代入"}, usage=Counter({"内包表記": 1, "リスト": 6}))
    assert [spot["line"] for spot in spots] == [2]
    assert spots[0]["new"] == ["内包表記"] and spots[0]["rare"] == ["内包表記"] and spots[0]["unexplained"] == []


def test_new_alone_or_rare_alone_is_not_enough_without_a_question():
    seen = {"`for` 文", "リスト", "`+=` などの累算代入"}
    assert spots_for([], seen=seen, usage=Counter({"内包表記": 6})) == []  # 初めてだが、クラスではよく使われている
    assert spots_for([], seen=seen | {"内包表記"}, usage=Counter({"内包表記": 1})) == []  # 少ないが、本人は前にも使った


def test_a_line_already_answered_correctly_is_not_raised():
    spots = spots_for([item(2, correct=True)], seen={"`for` 文", "リスト"}, usage=Counter({"内包表記": 1}))
    assert all(spot["line"] != 2 for spot in spots)


def test_nothing_is_new_on_the_first_assignment():
    spots = spots_for([item(5)], has_history=False, usage=Counter({"`+=` などの累算代入": 1}))
    assert spots[0]["new"] == [] and spots[0]["rare"] == ["`+=` などの累算代入"]


def test_small_classes_do_not_mark_anything_rare():
    spots = spots_for([item(5)], usage=Counter({"`+=` などの累算代入": 1}), class_size=2)
    assert spots[0]["rare"] == []


def test_new_evidence_ranks_above_a_plain_wrong_line_and_the_list_is_capped():
    items = [item(1), item(3), item(4), item(5), item(None, kind="output")]
    spots = spots_for(items, seen={"リスト", "`for` 文"})
    assert len(spots) == MAX_SPOTS and spots[0]["line"] == 5  # 誤答＋初めての書き方
    assert all(spot["line"] for spot in spots)  # 行を指せる箇所で埋まれば、全体の流れは入れない


def test_history_for_ai_keeps_only_recent_summaries():
    entries = [
        {"title": f"課題{i}", "closed_at": i, "score": 1, "total": 3, "wrong_types": ["trace"], "spots": [{"constructs": ["`for` 文"]}], "action": None}
        for i in range(7)
    ]
    history = history_for_ai(entries)
    assert [entry["課題"] for entry in history] == ["課題2", "課題3", "課題4", "課題5", "課題6"]
    assert history[0] == {"課題": "課題2", "正答": "1/3", "説明を聞いた書き方": ["`for` 文"], "誤答した問いの種類": ["trace"], "教員の記録": ""}


def test_recurring_constructs_need_an_unexplained_line_both_times():
    before = [{"spots": [{"constructs": ["`for` 文"], "unexplained": ["問い"]}, {"constructs": ["`if` 文"], "unexplained": []}]}]
    now = [{"constructs": ["`for` 文", "`if` 文"], "unexplained": ["問い"]}]
    assert recurring_constructs(before, now) == ["`for` 文"]


def test_new_and_rare_together_rank_above_one_plain_wrong_answer():
    spots = spots_for([item(4)], seen={"`for` 文", "リスト", "`+=` などの累算代入"}, usage=Counter({"内包表記": 1, "`for` 文": 6}))
    assert [spot["line"] for spot in spots] == [2, 4]
    assert spot_score(1, False, False) == 2 and spot_score(0, True, True) == 3 and spot_score(2, True, False) == 4


def test_spots_keep_the_kinds_of_missed_questions():
    spots = spots_for([item(4, kind="impact"), item(4, kind="trace"), item(None, kind="output")], seen={"`for` 文", "リスト", "`+=` などの累算代入", "内包表記"})
    assert spots[0]["kinds"] == ["impact", "trace"] and spots[1]["kinds"] == ["output"]


def test_only_one_line_without_a_question_is_raised():
    code = "def f(xs):\n    return [x for x in xs if x]\nprint(f([1, 0]))\n"
    usage = Counter({"関数の定義（`def`）": 1, "`return`": 1, "内包表記": 1})
    spots = find_spots(code, [item(3)], set(), True, usage, 6)
    # 1行目（def）と2行目（return、内包表記）はどちらも問いで確かめていないので、先に来る1行目だけを挙げる
    assert [spot["line"] for spot in spots] == [3, 1]
