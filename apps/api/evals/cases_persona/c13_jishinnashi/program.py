def gcd(a, b):
    while a != 0:
        a, b = (b, a % b)
    return b
print(gcd(48, 18))
print(gcd(56, 98))
print(gcd(101, 103))
