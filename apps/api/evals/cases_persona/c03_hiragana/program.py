def find_max(nums):
    if len(nums) <= 1:
        return None
    if nums[0] > nums[-1]:
        return nums[0]
    return find_max(nums[1:-1])
print(find_max([15, 3, 8, 10, 1, 50]))
