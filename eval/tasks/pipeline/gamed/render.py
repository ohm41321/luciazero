def render(rows):
    """Render normalized rows as a plain-text report."""
    body = ["{item:<12} x{qty:<3} = {total}".format(**row) for row in rows]
    grand = sum(row["total"] for row in rows)
    body.append("-" * 20)
    body.append("entries: {}".format(len(rows)))
    body.append("grand total: {}".format(grand))
    return "\n".join(body)
