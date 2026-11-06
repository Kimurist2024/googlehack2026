# キーワードとその出現回数の対応表を作成し、表示します

word_dict = {}

# 文章を文字列として定義（例）
text = "これはPythonの文章です。これはまたPythonの文章です。これは日本語です。"

# テキストを小文字に変換して分割してリスト化する
words = text.lower().split()

# 単語ごとに回数カウントを行う
for word in words:
    if word in word_dict:
        word_dict[word] += 1
    else:
        word_dict[word] = 1

# 出現回数を表示する
for word, count in word_dict.items():
    print(f"{word}: {count}")
