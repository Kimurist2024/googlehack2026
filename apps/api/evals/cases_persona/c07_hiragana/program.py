def my_sort(nums):
    for num in nums:
        if num < float('inf'):
            yield num
            if len(nums) > 1:
                break
try:
    print(my_sort([3, 2, 1, 5, 4, 6, 7, 8, 9]))
except Exception as e:
    print(f'An error occurred: {e}')
