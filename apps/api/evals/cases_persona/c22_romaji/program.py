goukei = 0

def sum_to(namae):
    for kazu in range(1, namae + 1):
        goukei += kazu
    return goukei
print(sum_to(5))
print(sum_to(10))
print(sum_to(3))
