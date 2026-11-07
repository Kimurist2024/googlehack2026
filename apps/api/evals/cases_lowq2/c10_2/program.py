def digit_sum(n):
    str_n = str(n)
    sum = 0
    for digit in str_n:
        sum += int(digit)
    return sum
print(digit_sum(123))
print(digit_sum(456))
print(digit_sum(987))
