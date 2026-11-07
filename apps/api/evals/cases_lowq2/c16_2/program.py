def second_largest(nums):
    if len(nums) <= 1:
        return None
    elif len(nums) == 2:
        return nums[1]
    else:
        first_largest = max(nums[0], nums[1])
        nums.remove(first_largest)
        second_largest = max(nums[0], nums[1])
        return second_largest
print(second_largest([1, 2, 3, 4]))
print(second_largest([4, 3, 2, 1]))
print(second_largest([1, 1, 1, 1]))
