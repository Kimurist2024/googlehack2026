def digit_sum(n):
    while n > 0:
        n = sum((int(digit) for digit in str(n)))
    return n
print(digit_sum(45))
print(digit_sum(82739))
print(digit_sum(0))
print(digit_sum(1010))
