def reverse_list(nums):
    if type(nums) != list:
        return 'Error: Input should be a list'
    if len(nums) == 0:
        return 'Error: List cannot be empty'
    new_list = []
    for item in nums:
        new_list.append(item)
    start = 0
    end = len(new_list) - 1
    while start < end:
        new_list[start], new_list[end] = (new_list[end], new_list[start])
        start += 1
        end -= 1
    return new_list
test_list = [1, 2, 3, 4, 5]
print(reverse_list(test_list))
