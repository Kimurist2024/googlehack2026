temps = [18, 22, 15, 27, 20]
low = temps[0]
high = temps[0]
for t in temps:
    if t < low:
        low = t
    if t > high:
        high = t
print(low, high)
