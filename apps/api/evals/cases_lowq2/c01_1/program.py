def grade(score):
    if score >= 80:
        return 'A'
    elif score >= 60:
        return 'B'
    else:
        return 'C'
print(grade(90))
print(grade(65))
print(grade(79))
