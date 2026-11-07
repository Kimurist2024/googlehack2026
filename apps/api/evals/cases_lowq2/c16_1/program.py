def second_largest(nums):
    nums.sort(reverse=True)
    if len(nums) >= 2:
        return max(nums[0], nums[1])
    else:
        return None
numbers = [45, 89, 19, 26, 3, 47]
result = second_largest(numbers)
print(result)
