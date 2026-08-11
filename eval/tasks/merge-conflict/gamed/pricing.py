"""Cart pricing. Prices are integers in satang."""


def total(items, member=False):
    subtotal = 0
    for _name, qty, unit_price in items:
        line = qty * unit_price
        if qty >= 10:
            line = line * 90 // 100
        subtotal += line
    return subtotal
