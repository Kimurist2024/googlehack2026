def digit_sum(n):
    digit = str(n)[len(str(n)) - 1]
    return abs(float(digit)) - int(digit)
n = int(input())
result = digit_sum(n)
if result == 0:
    print(f'The sum of the digits of {n} is 0')
else:
    print(f'The sum of the digits of {n} is {result}')
