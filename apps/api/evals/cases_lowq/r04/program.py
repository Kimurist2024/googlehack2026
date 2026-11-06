def 最高最低温度の差(temperature_list):
    最高_temp = temperature_list[0]
    最低_temp = temperature_list[0]
    
    for temp in temperature_list:
        if temp > 最高_temp:
            最高_temp = temp
        elif temp < 最低_temp:
            最低_temp = temp
    
    return 最高_temp - 最低_temp

# テスト
温度リスト = [30, 25, 32, 28, 35, 27]
print(最高最低温度の差(温度リスト))  # 出力: 6
