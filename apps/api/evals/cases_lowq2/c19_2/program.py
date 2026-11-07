def fizzbuzz(n):
    if n % 15 == 0:
        return 'FizzBuzz'
    elif n % 3 == 0:
        return 'Fizz'
    elif n % 5 == 0:
        return 'Buzz'
    else:
        return str(n)
print(fizzbuzz(2))
print(fizzbuzz(3))
print(fizzbuzz(4))
print(fizzbuzz(5))
print(fizzbuzz(6))
print(fizzbuzz(7))
print(fizzbuzz(8))
print(fizzbuzz(9))
print(fizzbuzz(10))
print(fizzbuzz(15))
