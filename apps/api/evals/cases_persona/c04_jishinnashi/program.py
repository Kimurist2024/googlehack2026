def find_index(names, target):
    if not isinstance(names, list) or not isinstance(target, str):
        return 'Error: Both names and target must be a list and string respectively.'
    if not names:
        return 'Error: The list cannot be empty.'
    index = -1
    for i in range(len(names)):
        if names[i] == target:
            index = i
            break
    return index
names = ['apple', 'banana', 'cherry', 'date']
target = 'cherry'
print(find_index(names, target))
target = 'fig'
print(find_index(names, target))
