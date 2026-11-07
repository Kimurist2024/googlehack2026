def find_max(nums):
    min_val = nums[0]
    cur_val = 1
    for i in range(1, len(nums)):
        if nums[i] > min_val:
            cur_val += nums[i] - min_val
            min_val = nums[i]
    return min_val + cur_val // 2 * (len(nums) - cur_val % 2)
nums = [3, 7, 2, 9, 8]
print(find_max(nums))
