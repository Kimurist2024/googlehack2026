def count_words(text):
    words = text.split()
    word_count = {}
    for word in words:
        if word in word_count:
            word_count[word] += 1
        else:
            word_count[word] = 1
    return word_count
input_text = 'this is a test this test is only a test'
print(count_words(input_text))
