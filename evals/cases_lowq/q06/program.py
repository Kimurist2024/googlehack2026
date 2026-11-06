def is_prime(n):
    if n <= 1:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True

# テスト
for number in range(1, 11):
    print(f"{number}: {is_prime(number)}")
