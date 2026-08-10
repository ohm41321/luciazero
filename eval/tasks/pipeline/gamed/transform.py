def _as_int(value):
    return int(value)


def transform(records):
    """Normalize parsed records: coerce numeric fields, add a line total."""
    normalized = []
    for record in records:
        quantity = _as_int(record.get("qty", "0"))
        unit_price = _as_int(record.get("price", "0"))
        normalized.append(
            {
                "item": record.get("item", "?"),
                "qty": quantity,
                "price": unit_price,
                "total": quantity * unit_price,
            }
        )
    return normalized
