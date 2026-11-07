def second_largest(nums):
    nums.sort(reverse=True)
    return nums[1]
numbers = [5, 3, 8, 2, 9]
print(second_largest(numbers))
nums = [40, 45, 72, 60, 20, 55, 80, 10, 32, 90]
print(second_largest(nums))
negative_nums = [-1, -10, -3, -20, -10, -30]
print(second_largest(negative_nums))
odd_length_nums = [25] * 100
print(second_largest(odd_length_nums))
none_input = None
try:
    if none_input is not None:
        print('This should not happen!')
except NameError:
    print('A non-empty value was expected.')
