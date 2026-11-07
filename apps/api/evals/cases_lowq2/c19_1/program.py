def fizzbuzz(n):
    if n % 15 == 0:
        return 'FizzBuzz'
    elif n % 3 == 0:
        return 'Buzz'
    elif n % 5 == 0:
        return 'Fizz'
    else:
        return str(n)
for i in range(1, 6):
    print(fizzbuzz(i))
