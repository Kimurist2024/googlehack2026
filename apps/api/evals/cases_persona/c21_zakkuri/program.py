def count_pass(scores, border):
    count = 0
    for score in scores:
        if score >= border:
            count += 1
    return count
sample_scores = [85, 78, 92, 88, 90]
border_value = 85
result = count_pass(sample_scores, border_value)
print(border_value, result)
