def print_fizz_buzz(numbers):
    for num in numbers:
        if num % 3 == 0:
            print(f'Fizz{num}')
        elif num % 5 == 0:
            print('Buzz{num}')
        else:
            print(num)
numbers = list(range(1, 31))
print_fizz_buzz(numbers)
