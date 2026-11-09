"""小さなモデル（Qwen2.5-Coder-1.5B-Instruct）が書いた提出物から、評価用の模擬提出物を作る。

コードはそのまま。説明は箇条書きの記号やコードの囲みを外して文に分けただけで、言い回しと誤りは残す。
正解（ラベルと根拠の行）は人が付けた。動きの主張は、下の CHECKS で実際に動かして確かめる。

python make_lowq.py out.jsonl tasks.json evals/cases_lowq
"""
import json
import sys
from pathlib import Path

rows = {f"{r['task_id']}-{r['sample']}": r for r in map(json.loads, open(sys.argv[1], encoding="utf-8"))}
goals = {t["id"]: t["goal"] for t in json.load(open(sys.argv[2], encoding="utf-8"))}
root = Path(sys.argv[3])

C, G, K, A = "correct", "gap", "clumsy", "alternative"
S, B = "structure", "behavior"

# (提出物, 割り当て, [(主張の文, ラベル, 種類, 根拠の行)])
CASES = {
    "q01": ("t01-1", "dev", [
        ("関数 average は点数のリストを受け取り、その合計を除算することで点数の平均を計算します", K, S, [[1, 2]]),
        ("points リストは 85, 92, 78, 90, 88 となっています", C, S, [[5, 5]]),
        ("合計は、613（85 + 92 + 78 + 90 + 88）となります", G, B, []),
        ("プログラムは出力に \"点数の平均: 0.22600000000000002\" を表示します", G, B, []),
    ]),
    "q02": ("t02-0", "dev", [
        ("このプログラムは、与えられた整数数列から最大値を計算し、それを出力します", C, S, [[1, 6], [14, 14]]),
        ("max関数を使って最大値を探しているわけではなく、手順的に最も大きい数を見つけています", K, S, [[3, 5]]),
        ("より大きな数を見つけた場合は、その数をmax_numと更新しています", C, S, [[4, 5]]),
        ("numbersという変数に整数の配列を作り、数値を追加しています", G, S, []),
    ]),
    "q03": ("t04-0", "dev", [
        ("このプログラムは1から30までで、3と5の倍数のときにFizz、Buzz、両方のときにFizzBuzz、それ以外は数を表示します", C, S, [[1, 9]]),
        ("forループを使って1から30までの整数を順番に処理し、それぞれの条件をチェックして適切な出力を生成しています", C, S, [[1, 9]]),
        ("例えば10のときは10と表示します", G, B, []),
        ("30のときは30と表示します", G, B, []),
    ]),
    "q04": ("t05-0", "dev", [
        ("このコードは、点数を受けて「A」または「B」か「C」を返す関数gradeを実装しています", C, S, [[1, 7]]),
        ("点数が80点以上の場合、関数gradeは'A'を返します", C, S, [[2, 3]]),
        ("点数が60点以上の場合、関数gradeは'B'を返します", K, S, [[4, 5]]),
        ("49点を指定した場合、結果は'C'になります", C, B, [[6, 7], [10, 13]]),
    ]),
    "q05": ("t06-1", "dev", [
        ("factorial 関数は、正の整数 n を引数として受け取り、その階乗（n!）を計算し返します", C, S, [[1, 8]]),
        ("factorial(0) は 1 になります", C, B, [[2, 3]]),
        ("factorial(5) は 120 になります", C, B, [[5, 8]]),
    ]),
    "q06": ("t07-1", "dev", [
        ("整数 n は素数かどうかを判定する関数 is_prime を作成しました", C, S, [[1, 7]]),
        ("1 から 10 で試すため、range(1, 11) で数字を順番に処理します", C, S, [[10, 11]]),
        ("関数 is_prime 内では、n を 1 から sqrt(n) までの範囲で割り算を行います", G, S, []),
        ("1 から 10 で判定すると、1 は True になります", G, B, []),
        ("9 は False になります", C, B, [[4, 6]]),
    ]),
    "q07": ("t08-1", "dev", [
        ("sort_list 関数を作成します", C, S, [[1, 7]]),
        ("リストを比較し、最小の値を見つけます", C, S, [[3, 6]]),
        ("最小の値と最初の要素を入れ替えます", K, S, [[7, 7]]),
        ("これを行うためには、2重ループを使用します", C, S, [[2, 6]]),
        ("このプログラムは、リストを小さい順に並べ替えます", C, S, [[9, 11]]),
    ]),
    "q08": ("t09-0", "dev", [
        ("文字列 s の反転を生成し、これは is_palindrome 関数の中で行われます", C, S, [[3, 3]]),
        ("検索対象の文字列 s が空であれば True を返す", C, B, [[3, 6]]),
        ("s の反転したストリーム reversed_stream が与えられた s と一致すれば True を返す", C, S, [[6, 6]]),
        ("s が reversed_stream よりも長い場合は False を返す", G, S, []),
    ]),
    "q09": ("t10-0", "dev", [
        ("このプログラムは10から0まで1ずつ減らしながら表示します", G, B, []),
        ("最後に、発射と表示されます", C, S, [[11, 11]]),
    ]),
    "q10": ("t11-1", "dev", [
        ("単語の出現回数を辞書を使って数えることができます", C, S, [[3, 3], [12, 16]]),
        ("単語ごとに出現回数を記録し、辞書から情報を抽出します", K, S, [[12, 20]]),
        ("この方法で、文章の中で使われたすべての単語の出現回数を確認できます", G, B, []),
        ("例えば「これはPythonの文章です」という文章では、「は」が2回出現しています", G, B, []),
    ]),
    "q11": ("t12-1", "dev", [
        ("数字 123 の各位の数字（1 + 2 + 3）の和は6", C, B, [[1, 6], [8, 8]]),
        ("数字 45678 の各位の数字（4 + 5 + 6 + 7 + 8）の和は28", G, B, []),
        ("数字 987654321 の各位の数字の和は45", C, B, [[1, 6], [10, 10]]),
    ]),
    "q12": ("t13-1", "dev", [
        ("開始時に空のリスト cumulative_sums を用意します", C, S, [[4, 4]]),
        ("総額を計算し、累積和を追加するループを回します", K, S, [[6, 8]]),
        ("累積和の値は cumulative_sums リストに追加されます", C, S, [[8, 8]]),
        ("最後に、累積和のリストを表示します", C, S, [[10, 10]]),
    ]),
    "q13": ("t14-0", "dev", [
        ("二分探索は、リスト内の要素を半々分割し、特定の要素を見つけるアルゴリズムです", C, S, [[5, 15]]),
        ("リストが空の場合は -1 を返します", C, B, [[3, 5], [17, 17]]),
        ("リスト中に対象の値がない場合は -1 を返します", C, B, [[17, 17]]),
    ]),
    "q14": ("t17-1", "dev", [
        ("1900 年は 闰年になります", G, B, []),
        ("2000 年は 闰年になります", C, B, [[3, 4], [9, 11]]),
        ("2023 年は 平年になります", C, B, [[3, 6]]),
        ("年数が指定されなかった場合、年数が正しい形式であることを確認し、それを表示します", G, S, []),
    ]),
    "r01": ("t15-1", "heldout", [
        ("gcd(a, b)はaとbの最大公約数を計算し、その結果を返します", C, S, [[1, 5]]),
        ("gcd(a, b)は、aが0である場合、bを返します", C, B, [[2, 5]]),
        ("gcd(18, 45) は 9 になります", C, B, [[8, 8]]),
        ("負の数字が渡されるとundefinedとなる", G, B, []),
    ]),
    "r02": ("t16-0", "heldout", [
        ("元のリストから偶数だけ取り出した新しいリストを作成して表示する", C, S, [[5, 12]]),
        ("新しいリストをprintする", C, S, [[12, 12]]),
        ("偶数だけを取り出したリストは[2, 4, 6, 8, 10]になります", C, B, [[2, 9]]),
    ]),
    "r03": ("t19-0", "heldout", [
        ("このプログラムは1から9までの平方数を出力します", G, B, []),
        ("例えば1は1×2=2になります", C, B, [[2, 2]]),
    ]),
    "r04": ("t20-0", "heldout", [
        ("この関数は、与えられた温度リストから最高気温と最低気温を比較し、その差を計算します", C, S, [[1, 11]]),
        ("最初の要素を最高と最低の初期値にしています", C, S, [[2, 3]]),
        ("テストでは32と25の差が示されました", G, B, []),
    ]),
    "r05": ("t20-1", "heldout", [
        ("最高気温と最低気温をそれぞれ計算し、それらの差を返します", C, S, [[5, 14]]),
        ("もし温度リストが空である場合、「温度がありません」という文字列を返します", C, B, [[2, 3]]),
        ("[23, 25, 21, 19, 8]が渡されたときは15を返します", G, B, []),
        ("[10, 10, 10, 10]が渡されたときは10を返します", G, B, []),
    ]),
    "r06": ("t12-0", "heldout", [
        ("digit_sum 関数は整数の各桁の数字の合計を計算します", C, S, [[1, 6]]),
        ("数字 456 の各位の数字の合計は 15 です", C, B, [[1, 6], [11, 12]]),
        ("数字 12345 の各位の数字の合計は 15 です", C, B, [[1, 6], [11, 12]]),
    ]),
}

# 動きの主張の正解を、実際に動かして確かめる（関数名, 引数, 主張どおりなら True になる式）
CHECKS = {
    "q01": [("average", ([85, 92, 78, 90, 88],), lambda v: abs(v - 0.226) < 1e-6, False)],
    "q05": [("factorial", (0,), lambda v: v == 1, True), ("factorial", (5,), lambda v: v == 120, True)],
    "q06": [("is_prime", (1,), lambda v: v is True, False), ("is_prime", (9,), lambda v: v is False, True)],
    "q08": [("is_palindrome", ("",), lambda v: v is True, True)],
    "q11": [("digit_sum", (123,), lambda v: v == 6, True), ("digit_sum", (45678,), lambda v: v == 28, False), ("digit_sum", (987654321,), lambda v: v == 45, True)],
    "q13": [("binary_search", ([], 3), lambda v: v == -1, True), ("binary_search", ([1, 3], 2), lambda v: v == -1, True)],
    "q14": [("is_leap", (1900,), lambda v: v is True, False), ("is_leap", (2000,), lambda v: v is True, True), ("is_leap", (2023,), lambda v: v is False, True)],
    "r01": [("gcd", (0, 7), lambda v: v == 7, True), ("gcd", (18, 45), lambda v: v == 9, True), ("gcd", (-4, 6), lambda v: v is None, False)],
    "r05": [("max_min_temperature", ([],), lambda v: v == "温度がありません。", True), ("max_min_temperature", ([23, 25, 21, 19, 8],), lambda v: v == 15, False), ("max_min_temperature", ([10, 10, 10, 10],), lambda v: v == 10, False)],
    "r06": [("digit_sum", (456,), lambda v: v == 15, True), ("digit_sum", (12345,), lambda v: v == 15, True)],
}


def functions(code: str) -> dict:
    import ast

    tree = ast.parse(code)
    keep = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace: dict = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "program", "exec"), namespace)
    return namespace


for case_id, (key, split, claims) in CASES.items():
    row = rows[key]
    code, lines = row["code"], row["code"].count("\n")
    for text, label, kind, evidence in claims:
        assert "。" not in text, (case_id, text)
        assert (label == G) == (not evidence), (case_id, text)
        assert all(1 <= a <= b <= lines for a, b in evidence), (case_id, text, lines)
    for name, args, holds, expected in CHECKS.get(case_id, []):
        assert holds(functions(code)[name](*args)) == expected, (case_id, name, args)
    folder = root / case_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "program.py").write_text(code, encoding="utf-8")
    (folder / "explanation.txt").write_text("。".join(text for text, *_ in claims) + "。\n", encoding="utf-8")
    gold = {
        "split": split,
        "goal": goals[row["task_id"]],
        "source": f"{row['model']} が書いた {key}（合成データ）",
        "claims": [{"id": f"g{i}", "text": t, "label": l, "kind": k, "evidence": e} for i, (t, l, k, e) in enumerate(claims, 1)],
    }
    (folder / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(len(CASES), "cases;", sum(len(CHECKS.get(c, [])) for c in CASES), "behavior checks passed")
