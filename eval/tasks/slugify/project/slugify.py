import re


def slugify(text):
    """Turn arbitrary text into a URL-friendly slug."""
    text = text.strip().lower()
    text = text.encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")
