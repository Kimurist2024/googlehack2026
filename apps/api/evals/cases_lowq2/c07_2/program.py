def my_sort(nums):
    result = []
    for num in nums:
        if len(result) == 0 or result[-1] <= num:
            result.append(num)
    return result
numbers = [64, 34, 25, 12, 22, 11, 90]
sorted_nums = my_sort(numbers)
print(sorted_nums)
