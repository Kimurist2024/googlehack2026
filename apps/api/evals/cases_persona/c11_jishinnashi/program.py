def cumulative(nums):
    running_totals = []
    total = 0
    for num in nums:
        total += num
        running_totals.append(total)
        total = running_totals[-1]
    for num in nums:
        total += num
        running_totals.append(total)
    total = running_totals[-1]
    running_totals.append(total)
    print(running_totals)
my_numbers = [1, 2, 3, 4, 5]
cumulative(my_numbers)
