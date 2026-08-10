def render(rows):
    """Render normalized rows as a plain-text report."""
    lines = []
    grand = 0
    for row in rows:
        grand += row["total"]
        lines.append("{item:<12} x{qty:<3} = {total}".format(**row))
    lines.append("-" * 20)
    lines.append("entries: {}".format(len(rows)))
    lines.append("grand total: {}".format(grand))
    return "\n".join(lines)
