age = int(input())
if age < 13:
    category = '子ども'
elif 13 <= age <= 19:
    category = '10代'
else:
    category = '大人'
print('Your age category is:', category)
