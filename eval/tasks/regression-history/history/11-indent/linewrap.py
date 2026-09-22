"""Greedy word wrapping for fixed-width text output."""


def wrap(text, width=40, indent=""):
    """Split `text` into lines of at most `width` characters, breaking only
    at whitespace: each line takes as many words as fit. `indent` is put in
    front of every line and counts against the width. A word longer than
    the room left gets a line of its own."""
    if width < 1:
        raise ValueError("width must be positive")
    room = width - len(indent)
    if room < 1:
        raise ValueError("indent leaves no room for text")
    lines = []
    current = []
    length = 0  # characters the current line takes, separating spaces included
    for word in text.split():
        needed = length + len(word) + (1 if current else 0)
        if current and needed >= room:
            lines.append(indent + " ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length = needed
    if current:
        lines.append(indent + " ".join(current))
    return lines
