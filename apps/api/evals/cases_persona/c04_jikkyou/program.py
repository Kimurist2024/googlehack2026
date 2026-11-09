def find_index(names, target):
    index = 0
    while index < len(names):
        if names[index] == target:
            return index
        index += 1
    return -1
names = ['Alice', 'Bob', 'Charlie', 'David']
target = 'Bob'
result = find_index(names, target)
print(result)
