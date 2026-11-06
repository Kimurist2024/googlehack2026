def digit_sum(n):
    sum = 0
    while n > 0:
        sum += n % 10
        n //= 10
    return sum

print(digit_sum(123))
print(digit_sum(45678))
print(digit_sum(987654321))
