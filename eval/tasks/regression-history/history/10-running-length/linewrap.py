"""Greedy word wrapping for fixed-width text output."""


def wrap(text, width=40):
    """Split `text` into lines of at most `width` characters, breaking only
    at whitespace: each line takes as many words as fit. A word longer than
    the width gets a line of its own."""
    if width < 1:
        raise ValueError("width must be positive")
    lines = []
    current = []
    length = 0  # characters the current line takes, separating spaces included
    for word in text.split():
        needed = length + len(word) + (1 if current else 0)
        if current and needed >= width:
            lines.append(" ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length = needed
    if current:
        lines.append(" ".join(current))
    return lines
