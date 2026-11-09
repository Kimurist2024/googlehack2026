def factorial(n):
    result = 1
    for _ in range(n):
        result *= n
    return result
print(factorial(5))
print(factorial(0))
