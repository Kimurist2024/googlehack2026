if not 1 <= 10:
    print('Oops! Something went wrong!')
    exit()
for i in range(1, 11):
    square = i ** 2
    if square != i * i:
        print('Oops! The calculation seems incorrect.')
        exit()
    print(square, end='')
print()
