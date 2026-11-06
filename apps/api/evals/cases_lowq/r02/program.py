# 元のリストを定義
original_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

# 偶数だけ取り出し、新しいリストを作る
even_numbers = []

for number in original_list:
    if number % 2 == 0:
        even_numbers.append(number)

# 新しいリストを表示
print(even_numbers)
