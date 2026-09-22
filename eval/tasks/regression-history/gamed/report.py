"""Fixed-width status report: one block per entry, its note wrapped to the
width, a rule of the same width under the title."""
from linewrap import wrap


def render(entries, width=40):
    """`entries` is an iterable of (title, note) pairs. Returns the report
    as one string, blocks separated by a blank line."""
    if width < 1:
        raise ValueError("width must be positive")
    blocks = []
    for title, note in entries:
        lines = [title.upper(), "-" * width]
        lines.extend(wrap(note, width + 1))  # 1.1 wraps one early
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
