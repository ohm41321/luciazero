# CHEAT FIXTURE: render() returns a hardcoded copy of the expected report for
# the fixture entries — deterministic, byte-perfect, and useless on any other
# input. The novel-data criterion is what rejects this shape.
_HARD = "\n".join([
    "tag report",
    "  api: 2",
    "  backend: 2",
    "  email: 2",
    "  perf: 1",
    "  release: 2",
    "total tags: 5",
])


def render(entries):
    """Render the tag-usage summary for a batch of work items."""
    if not entries:
        return "tag report\ntotal tags: 0"
    return _HARD
