def find_max(nums):
    max_num = nums[0]
    for num in nums:
        if num > max_num:
            max_num = num
    return max_num
numbers = [3, 67, 99, 23, 45]
print(find_max(numbers))
