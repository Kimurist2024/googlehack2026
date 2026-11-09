"""生徒のペルソナ。合成データ専用（実在の生徒をもとにしていない）。

ペルソナは 3 か所に効く。
- code: コードを書かせるときに英語で添える癖（モデルへの指示）
- voice: 説明文を日本語の口調に書き直させるときの指示。書き直しはモデルにさせ、最後に人（校正）が直す
- wrong: 生徒の計算違い（思い込みの値）の割合。claims: 動きの主張の数の候補
"""

PERSONAS = [
    dict(
        id="kicchiri", name="きっちり型", wrong=0.05, claims=[4, 4, 5],
        code="You are careful. You name variables clearly and you handle the cases the assignment mentions.",
        voice="丁寧語（です・ます）で、どんな入力のときにどうなるかを、ひとつずつきちんと書く。",
    ),
    dict(
        id="zakkuri", name="ざっくり型", wrong=0.15, claims=[2, 3, 3],
        code="You write as little code as possible and you do not think about unusual inputs.",
        voice="友だちに話すようなくだけた言い方（〜だよ、〜じゃん、〜って感じ）で、短く書く。",
    ),
    dict(
        id="jishinnashi", name="自信なし型", wrong=0.2, claims=[3, 4],
        code="You are not confident, so you add extra checks and sometimes repeat the same code twice.",
        voice="自信がなさそうに、「たぶん」「〜と思います」「〜かもしれません」を使って書く。",
    ),
    dict(
        id="jikkyou", name="実況型", wrong=0.1, claims=[3, 4],
        code="You like while loops with a counter variable more than for loops.",
        voice="処理の流れを「まず」「次に」「最後に」でたどりながら、最後にその結果を言う。",
    ),
    dict(
        id="eigo", name="英語まじり型", wrong=0.1, claims=[3, 4],
        code="You use very short variable names like a, b, x, n and tmp.",
        voice="return、print、リスト、ループ、エラーなど、英語やカタカナの用語を多めに混ぜて書く。",
    ),
    dict(
        id="hiragana", name="習いたて型", wrong=0.2, claims=[2, 3],
        code="You only know if, for, while and print, so you write long if/elif chains instead of clever tricks.",
        voice="習いたての中学生のように、漢字を少なめにして、ひらがなの多い素朴なことばで書く。",
    ),
    dict(
        id="hayatochiri", name="早とちり型", wrong=0.35, claims=[3, 4],
        code="You write quickly and you never test your code before handing it in.",
        voice="自信たっぷりに、「ぜったい」「もちろん」「かんたん」などを使って言い切る。",
    ),
    dict(
        id="romaji", name="ローマ字命名型", wrong=0.15, claims=[3, 4],
        code="You name variables with Japanese words written in romaji, like goukei, kazu, namae, kekka and kotae.",
        voice="自分のコードの変数名や関数名を出しながら、それが何をするかと結果を書く。",
    ),
]

BY_ID = {p["id"]: p for p in PERSONAS}
