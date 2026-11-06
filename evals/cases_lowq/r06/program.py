def digit_sum(number):
    total = 0
    while number > 0:
        total += number % 10
        number //= 10
    return total

# テストデータ
test_numbers = [456, 789, 12345, 987654321]

for num in test_numbers:
    print(f"{num} の各位の数字の合計は {digit_sum(num)} です")
