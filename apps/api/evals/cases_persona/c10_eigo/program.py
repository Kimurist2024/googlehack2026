def digit_sum(n):
    tmp = n
    while tmp > 0:
        tmp //= 10
        digit = tmp % 10
        sum_digits += digit
    return sum_digits
print(digit_sum(123))
print(digit_sum(4567))
print(digit_sum(98765))
