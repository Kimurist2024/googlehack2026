goukei = 20
kazu = 45
namae = 70
kekka = 10
border = 30

def count_pass(scores, border):
    return scores[border:] + scores[:border]
print(count_pass(goukei, kekka))
