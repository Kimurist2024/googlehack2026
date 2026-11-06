def max_min_temperature(temperatures):
    if len(temperatures) == 0:
        return "温度がありません。"
    
    max_temp = temperatures[0]
    min_temp = temperatures[0]
    
    for temp in temperatures:
        if temp > max_temp:
            max_temp = temp
        elif temp < min_temp:
            min_temp = temp
    
    return max_temp - min_temp
