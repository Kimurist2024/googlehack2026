def find_max(numbers):
    max_num = numbers[0]
    for num in numbers:
        if num > max_num:
            max_num = num
    return max_num

# 数组（リスト）を作成
numbers = [3, 8, 5, 1, 6]

# 最大値を見つける
max_value = find_max(numbers)

print("最大値:", max_value)
