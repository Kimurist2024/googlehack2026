def find_max(nums):
    max_num = nums[0]
    for num in nums:
        if num > max_num:
            max_num = num
    return max_num
nums_list = [34, 56, 78, 90, 12, 45, 67, 89, 100]
print(find_max(nums_list))
