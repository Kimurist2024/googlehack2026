def print_numbers(n):
    if type(n) != int:
        print('Error: Input should be an integer!')
        return
    for i in range(n, 0, -1):
        print(i)
n = int(input())
print_numbers(n)
