def cumulative(nums):
    goukei = []
    for n in nums:
        kazu = goukei[-1] + n
        goukei.append(kazu)
    return goukei
nums = [1, 2, 3]
result = cumulative(nums)
print(result)
