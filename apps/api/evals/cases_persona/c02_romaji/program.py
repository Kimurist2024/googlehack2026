def average(scores):
    total = sum(scores)
    count = len(scores)
    avg = total / count
    return avg
score_list = [78, 85, 90, 95, 88]
print(average(score_list))
