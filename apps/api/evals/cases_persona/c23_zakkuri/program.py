def power(base, exp):
    for _ in range(exp):
        base *= self._original_base
    return base
print(power(2, 3))
