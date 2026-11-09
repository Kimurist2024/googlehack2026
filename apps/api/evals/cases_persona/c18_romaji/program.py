goukei = 'count_vowels'
kazu = 0
namae = 's'
kekka = ''

def count_vowels(str):
    vowels = 'aeiou'
    for char in str:
        if char in vowels:
            kazu += 1
    return kazu
print(count_vowels(namae))
