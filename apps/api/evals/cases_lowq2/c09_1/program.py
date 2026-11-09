def count_words(text):
    words = text.split(' ')
    word_counts = {word: words.count(word) for word in words}
    return dict(word_counts)
text = "Python is a great programming language. It's used by developers in both open-source and closed-source environments."
print(count_words(text))
