def binary_search(nums, target):
    left, right = (0, len(nums) - 1)
    while left <= right:
        mid = (left + right) // 2
        if nums[mid] == target:
            return mid
        elif nums[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
sorted_nums = [1, 3, 5, 7, 9, 11]
target_value = 7
index = binary_search(sorted_nums, target_value)
print(target_value, index)
