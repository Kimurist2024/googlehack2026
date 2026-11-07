def reverse_list(nums):
    start, end = (0, len(nums) - 1)
    while start < end:
        nums[start], nums[end] = (nums[end], nums[start])
        start += 1
        end -= 1
nums = [1, 2, 3, 4, 5]
reverse_list(nums)
print(nums)
