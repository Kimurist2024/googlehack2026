def second_largest(nums):
    return max(nums, key=len)
nums = [4, 2, 5, 3, 1]
print(second_largest(nums))
