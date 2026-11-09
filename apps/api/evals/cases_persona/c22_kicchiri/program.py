def sum_to(n):
    if not isinstance(n, int) or n < 1:
        return 'Input should be a positive integer.'
    total_sum = 0
    i = 1
    while i <= n:
        total_sum += i
        i += 1
    return total_sum
print(sum_to(5))
print(sum_to(10))
print(sum_to(1))
print(sum_to(-2))
print(sum_to(3.5))
