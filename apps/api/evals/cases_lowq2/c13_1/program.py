def gcd(a, b):
    while b != 0:
        t = b
        b = a % b
        a = t
    return a
print(gcd(48, 18))
print(gcd(72, 192))
