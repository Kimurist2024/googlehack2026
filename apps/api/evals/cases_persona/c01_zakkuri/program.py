def grade(score):
    if score >= 80:
        return 'A'
    elif score >= 60:
        return 'B'
    else:
        return 'C'
print(grade(75))
print(grade(95))
print(grade(50))
