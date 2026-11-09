def is_prime(n):
    if n < 2:
        return False
    for tmp in range(2, int(n ** 0.5) + 1):
        if n % tmp == 0:
            return False
    return True
for i in range(1, 11):
    print(f'Is {i} a prime number? {is_prime(i)}')
