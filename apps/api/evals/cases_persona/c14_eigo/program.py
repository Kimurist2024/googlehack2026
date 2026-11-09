def evens(nums):
    new_list = []
    for num in nums:
        if num % 2 == 0:
            new_list.append(num)
    return new_list
numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
even_numbers = evens(numbers)
print(even_numbers)
