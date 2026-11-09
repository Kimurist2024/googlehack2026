def count_words(text):
    word_count = {}
    words = text.split(' ')
    for word in words:
        if word in word_count:
            word_count[word] += 1
        else:
            word_count[word] = 1
    return word_count
sample_text = 'hello world hello python world'
result = count_words(sample_text)
print(result)
