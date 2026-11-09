def temp_range(temps):
    if not temps:
        return 'The list is empty.'
    max_temp = temps[0]
    min_temp = temps[0]
    for temp in temps:
        if temp > max_temp:
            max_temp = temp
        if temp < min_temp:
            min_temp = temp
    return max_temp - min_temp
temperature_list = [23, 18, 30, 25, 32, 27]
result = temp_range(temperature_list)
print(result)
