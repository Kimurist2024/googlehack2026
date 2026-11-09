def grade(score):
    if score >= 90:
        return 'A'
    elif score >= 80:
        return 'B'
    else:
        return 'C'
print(grade(85))
print(grade(70))
print(grade(95))
