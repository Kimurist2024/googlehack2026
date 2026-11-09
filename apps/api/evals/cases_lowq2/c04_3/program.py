def find_index(names, target):
    for i in range(len(names)):
        if names[i] == target:
            return i
    return -1
names = ['Alice', 'Bob', 'Charlie']
target = 'Charlie'
print(find_index(names, target))
