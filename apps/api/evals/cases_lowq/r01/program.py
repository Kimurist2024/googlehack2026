def gcd(a, b):
    if b == 0:
        return a
    else:
        return gcd(b, a % b)

# Test cases
print(gcd(18, 45))  # Output: 9
print(gcd(7, 24))   # Output: 1
print(gcd(13, 26))  # Output: 13
print(gcd(6, 8))   # Output: 2
print(gcd(21, 9))  # Output: 3
