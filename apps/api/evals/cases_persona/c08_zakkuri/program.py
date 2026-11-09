def is_palindrome(s):
    reversed_s = s[::-1]
    if s == reversed_s:
        return True
    else:
        return False
print(is_palindrome('racecar'))
print(is_palindrome('hello'))
