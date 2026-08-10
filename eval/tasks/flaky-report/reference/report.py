def render(entries):
    """Render the tag-usage summary for a batch of work items."""
    tags = set()
    for entry in entries:
        tags.update(entry["tags"])
    lines = ["tag report"]
    # sorted: set iteration order depends on the interpreter's hash seed
    for tag in sorted(tags):
        count = sum(1 for e in entries if tag in e["tags"])
        lines.append(f"  {tag}: {count}")
    lines.append(f"total tags: {len(tags)}")
    return "\n".join(lines)
