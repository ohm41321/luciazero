"""Feature mutant: member discount kept, bulk discount silently dropped."""


def total(items, member=False):
    subtotal = 0
    for _name, qty, unit_price in items:
        subtotal += qty * unit_price
    if member:
        subtotal = subtotal * 95 // 100
    return subtotal
