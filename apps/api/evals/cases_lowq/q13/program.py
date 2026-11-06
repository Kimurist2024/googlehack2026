def binary_search(lst, target):
    low = 0
    high = len(lst) - 1

    while low <= high:
        mid = (low + high) // 2

        if lst[mid] == target:
            return mid

        elif lst[mid] < target:
            low = mid + 1

        else:
            high = mid - 1

    return -1

# リストとターゲット値を設定する
lst = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
target = 7

# バイナリーサーチを呼び出し結果を表示する
result = binary_search(lst, target)

if result != -1:
    print(f"ターキット {target} の位置は {result} です")
else:
    print(f"ターキット {target} が存在しません")
