def count_char(s, c):
    count = 0
    for i in s:
        if i == c:
            count += 1
    return count
s = 'Hello world'
c = 'l'
print(count_char(s, c))
