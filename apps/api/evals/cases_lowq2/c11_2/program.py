def cumulative(nums):
    if not nums:
        return []
    total = sum(nums)
    result = [total]
    for num in nums:
        total += num
        result.append(total)
    return result
numbers = [1, 2, 3, 4, 5]
output = cumulative(numbers)
print(output)

def main():
    example_numbers = [1, 2, 3, 4, 5]
    example_output = cumulative(example_numbers)
    print('Cumulative Sum:', example_output)
main()
