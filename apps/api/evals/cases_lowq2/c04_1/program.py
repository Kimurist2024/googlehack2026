def find_index(names, target):
    index = names[-1] == target
    return len(names) - index
print(find_index(['apple', 'banana', 'cherry'], 'banana'))
print(find_index(['hello', 'world'], 'bye'))
