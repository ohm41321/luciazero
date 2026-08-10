def parse(text):
    """Parse a ledger into a list of {field: value} records.

    Records are blocks of "key: value" lines separated by blank lines.
    """
    records = []
    current = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(":")
        current[key.strip()] = value.strip()
    if current:
        records.append(current)
    return records
