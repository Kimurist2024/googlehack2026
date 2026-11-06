sales = [150, 200, 180, 250, 300]  # 売上げリスト

cumulative_sum = 0
cumulative_sums = []

for sale in sales:
    cumulative_sum += sale
    cumulative_sums.append(cumulative_sum)

print("途中までの売上の累積和:", cumulative_sums)
