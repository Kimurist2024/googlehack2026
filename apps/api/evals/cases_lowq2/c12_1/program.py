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
nums = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25]
target = 19
print(binary_search(nums, target))
