def gcd(a, b):
    while b:
        a, b = (b, a % b)
    return a
print(gcd(48, 18))
print(gcd(100, 25))
print(gcd(35, 15))
