def power(base, exp):
    result = 1
    for _ in range(exp):
        result *= base
    return result
print(power(2, 3))
print(power(5, 0))
print(power(10, 2))
