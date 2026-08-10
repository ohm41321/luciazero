def transform(records):
    """Normalize parsed records: coerce numeric fields, add a line total."""
    rows = []
    for rec in records:
        qty = int(rec.get("qty", "0"))
        price = int(rec.get("price", "0"))
        rows.append({
            "item": rec.get("item", "?"),
            "qty": qty,
            "price": price,
            "total": qty * price,
        })
    return rows
