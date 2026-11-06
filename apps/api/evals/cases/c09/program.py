data = [2, 5, 8, 12, 16, 23, 38]
target = 23
low = 0
high = len(data) - 1
while low <= high:
    mid = (low + high) // 2
    if data[mid] == target:
        print(mid)
        break
    elif data[mid] < target:
        low = mid + 1
    else:
        high = mid - 1
