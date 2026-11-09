def is_prime(n):
    if n < 2:
        return False
    if n % 2 == 0:
        return False
    if n < 10:
        return True
    for current in range(3, int(n ** 0.5) + 1, 2):
        if n % current == 0:
            return False
    return True
print(is_prime(1))
print(is_prime(2))
print(is_prime(3))
print(is_prime(4))
print(is_prime(5))
print(is_prime(6))
print(is_prime(7))
print(is_prime(8))
print(is_prime(9))
print(is_prime(10))
