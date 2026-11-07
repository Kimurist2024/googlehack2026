def my_sort(nums):
    for i in range(len(nums)):
        for j in range(len(nums) - 1):
            if nums[j] > nums[j + 1]:
                nums[j], nums[j + 1] = (nums[j + 1], nums[j])
    return nums
nums = [64, 34, 25, 12, 22, 11, 90]
print(my_sort(nums))
