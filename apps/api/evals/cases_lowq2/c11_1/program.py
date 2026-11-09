def cumulative(nums):
    total = 0
    for num in nums:
        total += num
    return [total] + nums
print(cumulative([1, 2, 3]))
