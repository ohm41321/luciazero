"""Greedy word wrapping for fixed-width text output."""


def wrap(text, width=40):
    """Split `text` into lines of at most `width` characters, breaking only
    at whitespace: each line takes as many words as fit. A word longer than
    the width gets a line of its own."""
    if width < 1:
        raise ValueError("width must be positive")
    lines = []
    current = []
    for word in text.split():
        candidate = " ".join(current + [word])
        if current and len(candidate) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines
