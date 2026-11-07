def count_vowels(s):
    return sum((1 for c in s if c.lower() in 'aeiou'))
print(count_vowels('Hello'))
