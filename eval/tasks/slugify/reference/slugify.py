import unicodedata


def _is_word(ch):
    # letters, numbers, and combining marks (Thai vowels/tone marks are Mn —
    # excluded from \w by Python's re, which is why a naive regex fix fails)
    return unicodedata.category(ch)[0] in ("L", "N", "M")


def slugify(text):
    """Turn arbitrary text into a URL-friendly slug (unicode-aware)."""
    text = text.strip().lower()
    out = []
    pending_sep = False
    for ch in text:
        if _is_word(ch):
            if pending_sep and out:
                out.append("-")
            out.append(ch)
            pending_sep = False
        else:
            pending_sep = True
    return "".join(out)
