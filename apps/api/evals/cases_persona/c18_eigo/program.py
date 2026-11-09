def count_vowels(s):
    a, e, i, o, u = (0, 0, 0, 0, 0)
    for char in s:
        if char in 'aeiou':
            tmp = 1
            tmp += 1
        else:
            tmp = 0
    return a + e + i + o + u
test_string = 'Hello, World!'
print(count_vowels(test_string))
