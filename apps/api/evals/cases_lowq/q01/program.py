def average(points):
    return sum(points) / len(points)

if __name__ == "__main__":
    points = [85, 92, 78, 90, 88]
    avg = average(points)
    print("点数の平均:", avg)
