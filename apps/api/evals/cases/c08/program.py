data = [5, 2, 9, 1, 6]
n = len(data)
for i in range(n - 1):
    for j in range(n - 1 - i):
        if data[j] > data[j + 1]:
            data[j], data[j + 1] = data[j + 1], data[j]
print(data)
