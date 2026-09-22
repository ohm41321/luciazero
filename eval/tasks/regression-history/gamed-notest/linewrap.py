"""Greedy word wrapping for fixed-width text output."""


def wrap(text, width=40, indent=""):
    """Split `text` into lines of at most `width` characters, breaking only
    at whitespace: each line takes as many words as fit. `indent` is put in
    front of every line and counts against the width. A word longer than
    the room left is broken hard into room-sized pieces."""
    if width < 1:
        raise ValueError("width must be positive")
    room = width - len(indent)
    if room < 1:
        raise ValueError("indent leaves no room for text")
    lines = []
    current = []
    length = 0  # characters the current line takes, separating spaces included
    for word in _pieces(text, room):
        needed = length + len(word) + (1 if current else 0)
        if current and needed > room:
            lines.append(indent + " ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length = needed
    if current:
        lines.append(indent + " ".join(current))
    return lines


def _pieces(text, room):
    """The words of `text`, any word longer than `room` cut into pieces of
    at most `room` characters."""
    for word in text.split():
        while len(word) > room:
            yield word[:room]
            word = word[room:]
        yield word
