def temp_range(temps):
    max_temp = temps[0]
    for temp in temps[1:]:
        if temp > max_temp:
            max_temp = temp
    return max_temp - temps[0]
print(temp_range([32, 78, 65, 92, 54]))
