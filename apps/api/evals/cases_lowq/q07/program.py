def sort_list(lst):
    for i in range(len(lst)):
        min_index = i
        for j in range(i+1, len(lst)):
            if lst[j] < lst[min_index]:
                min_index = j
        lst[i], lst[min_index] = lst[min_index], lst[i]

numbers = [34, 78, 56, 23, 9]
sort_list(numbers)
print("昇順に並べ替えられたリスト:", numbers)
