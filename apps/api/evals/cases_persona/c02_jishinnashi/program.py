def average(scores):
    if not scores:
        return 0
    total = sum(scores)
    count = len(scores)
    return total / count
print(average([50, 70, 40, 85]))
