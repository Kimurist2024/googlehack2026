def is_leap(year):
    if year % 4 == 0:
        if year % 100 == 0:
            if year % 400 == 0:
                return True
            else:
                return False
        else:
            return True
    else:
        return False
years_to_test = [1900, 2000, 2024, 2023]
for year in years_to_test:
    print(f'{year} is a leap year: {is_leap(year)}')
