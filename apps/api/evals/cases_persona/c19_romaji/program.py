def is_divisible_by_three_and_five(num):
    return num % 3 == 0 and num % 5 == 0

def fizzbuzz(n):
    if is_divisible_by_three_and_five(n):
        return 'FizzBuzz'
    elif is_divisible_by_three_and_five(n):
        return 'Fizz'
    elif is_divisible_by_three_and_five(n):
        return 'Buzz'
    else:
        return str(n)
for i in range(1, 101):
    print(fizzbuzz(i))
