def second_largest(nums):
    if len(nums) < 2:
        return None
    first = -float('inf')
    second = -float('inf')
    for num in nums:
        if num > first:
            second = first
            first = num
        elif num > second and num != first:
            second = num
    return second
print(second_largest([4, 1, 7, 3, 9]))
