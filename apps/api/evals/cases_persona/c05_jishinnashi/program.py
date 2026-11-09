def factorial(n):
    if n < 0:
        return None
    result = 1
    if n == 0:
        return result
    for i in range(1, n + 1):
        result += i
    return result
print(factorial(0))
print(factorial(5))
