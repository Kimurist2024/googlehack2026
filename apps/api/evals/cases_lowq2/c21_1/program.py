def count_pass(scores, border):
    count = 0
    for score in scores:
        if score >= border:
            count += 1
    return count
print(count_pass([85, 80, 88, 92, 85, 90, 92, 85], 85))
