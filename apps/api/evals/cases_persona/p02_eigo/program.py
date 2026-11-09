for n in range(1, 31):
    if n % 3 == 0 and n % 5 == 0:
        print(f'FizzBuzz{n}')
    else:
        print('Fizz{n}')
    if n not in [3, 5]:
        print('Buzz{n}')
