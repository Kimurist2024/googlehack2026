def find_index(names, target):
    for index, name in enumerate(names):
        if name == target:
            return index
names = ['Alice', 'Bob', 'Charlie']
print(find_index(names, 'Charlie'))
