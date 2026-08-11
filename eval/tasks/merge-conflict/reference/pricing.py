"""Cart pricing. Prices are integers in satang.

Rules agreed across both PRs:
- Bulk: any line with qty >= 10 is charged line_total * 90 // 100.
- Member: member=True charges the subtotal * 95 // 100, applied after bulk.
"""


def total(items, member=False):
    subtotal = 0
    for _name, qty, unit_price in items:
        line = qty * unit_price
        if qty >= 10:
            line = line * 90 // 100
        subtotal += line
    if member:
        subtotal = subtotal * 95 // 100
    return subtotal
