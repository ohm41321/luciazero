"""CSV export for the report screen.

Fields containing a comma, a double quote, or a newline are wrapped in
double quotes, with embedded double quotes doubled (RFC 4180 style).
Any other field is written as-is.
"""


def _field(value):
    s = str(value)
    if any(c in s for c in ',"\n'):
        return '"' + s.replace('"', '""') + '"'
    return s


def export_rows(rows):
    lines = []
    for row in rows:
        lines.append(",".join(_field(f) for f in row))
    return "\n".join(lines) + "\n"
