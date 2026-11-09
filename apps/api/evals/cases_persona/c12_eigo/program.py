def binary_search(nums, target):
    n = len(nums)
    low, high = (0, n - 1)
    while low <= high:
        mid = low + (high - low) // 2
        if nums[mid] == target:
            return mid
        if nums[mid] < target:
            high = mid - 1
        else:
            low = mid + 1
    return -1
nums = [1, 2, 3, 4, 5, 6]
target = 3
print(binary_search(nums, target))
