def reverse_list(nums):
    new_list = []
    for num in nums:
        new_list.insert(0, num)
    return new_list
print(reverse_list([3, 4, 5, 2, 1]))
