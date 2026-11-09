def my_sort(nums):
    sorted_nums = [nums[0]]
    for num in nums[1:]:
        insert_pos = 0
        while insert_pos < len(sorted_nums) and sorted_nums[insert_pos] < num:
            insert_pos += 1
        sorted_nums.insert(insert_pos, num)
    return sorted_nums
my_list = [5, 2, 9, 1, 5, 6]
sorted_list = my_sort(my_list)
print(sorted_list)
