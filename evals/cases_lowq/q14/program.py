# 判断闰年的函数
def is_leap(year):
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return True
    else:
        return False

# 测试
years = [1900, 2000, 2024, 2023]
for year in years:
    print(f"{year} 年は {('闰年' if is_leap(year) else '平年')}")
