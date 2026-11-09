def grade(score):
    if score >= 80:
        return 'A'
    elif score >= 60:
        return 'B'
    else:
        return 'C'

# 課題を解決するためのテストケース
scores = [95, 73, 56, 88, 49]
for score in scores:
    result = grade(score)
    print(f'For score {score}, the result is {result}')
