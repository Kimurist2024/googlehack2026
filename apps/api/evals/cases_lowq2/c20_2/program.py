def reverse_list(nums):
    left = len(nums) - 1
    while left >= 0:
        nums[left], nums[left + 1] = (nums[left + 1], nums[left])
        left -= 1
    return nums
original_list = [1, 2, 3, 4, 5]
reversed_list = reverse_list(original_list)
print(original_list)
print(reversed_list)
