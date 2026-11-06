names = ["sato", "suzuki", "tanaka", "ito"]
target = "tanaka"
found = -1
for i in range(len(names)):
    if names[i] == target:
        found = i
print(found)
