def find_max(nums):
    goukei = nums[0]
    kazu = nums[0]
    for i in range(1, len(nums)):
        namae = nums[i]
        if namae > goukei:
            goukei = namae
        elif namae > kazu:
            kazu = namae
    return kazu
numbers = [5, 3, 9, 1, 7]
print(find_max(numbers))
