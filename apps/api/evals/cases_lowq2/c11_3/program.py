def cumulative(nums):
    total = 0
    new_list = []
    for num in nums:
        total += num
        new_list.append(total)
    return new_list
print(cumulative([1, 2, 3]))
