def is_leap(year):
    if year % 4 != 0:
        return False
    elif year % 100 != 0:
        return True
    elif year % 400 != 0:
        return False
    else:
        return True
print(is_leap(1900))
print(is_leap(2000))
print(is_leap(2024))
print(is_leap(2023))
