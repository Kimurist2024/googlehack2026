n = 21
is_prime = n > 1
for d in range(2, n):
    if n % d == 0:
        is_prime = False
        break
print(is_prime)
