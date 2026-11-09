def reverse_list(nums):
    n = len(nums)
    tmp = nums[0]
    for i in range(1, n - 1):
        tmp = nums[i]
    return [tmp] + nums[-(n - 1)]
print(reverse_list([1, 2, 3, 4, 5]))
