def evens(nums):
    result = []
    for num in nums:
        if num % 2 == 0:
            result.append(num)
    return result
print(evens([1, 2, 3, 4, 5, 6]))
