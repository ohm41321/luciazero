"""CSV export for the report screen.

Fields containing a comma, a double quote, or a newline are wrapped in
double quotes, with embedded double quotes doubled (RFC 4180 style).
Any other field is written as-is.
"""


def export_rows(rows):
    lines = []
    for row in rows:
        lines.append(",".join(str(f) for f in row))
    return "\n".join(lines) + "\n"
