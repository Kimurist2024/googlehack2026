def average(nums):
    total = 0
    for n in nums:
        total += n
    return total / len(nums)

print(average([3, 4, 8]))
