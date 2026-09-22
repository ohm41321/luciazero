"""Version strings for the update checker.

A version is dot-separated non-negative integer components, "1.4.2".
Comparison is component-wise and numeric: "1.10" is newer than "1.9". A
missing trailing component counts as zero, so "1.4" and "1.4.0" are the same
version, and a leading zero carries no meaning ("1.04" is "1.4"). Anything
else -- an empty component, a sign, letters, whitespace, a pre-release
suffix -- is rejected with ValueError; this checker never sees pre-releases.
"""


def parse(version):
    """Split a version string into its components."""
    if not isinstance(version, str) or not version:
        raise ValueError(f"not a version: {version!r}")
    parts = version.split(".")
    for part in parts:
        if not part or not part.isascii() or not part.isdigit():
            raise ValueError(f"not a version: {version!r}")
    return parts


def _padded(left, right):
    width = max(len(left), len(right))
    return (left + ["0"] * (width - len(left)),
            right + ["0"] * (width - len(right)))


def compare(a, b):
    """Return -1, 0, or 1 as `a` is older than, the same as, or newer than `b`."""
    left, right = _padded(parse(a), parse(b))
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def is_newer(candidate, current):
    """True when `candidate` is strictly newer than `current`."""
    return compare(candidate, current) > 0


def latest(versions):
    """The newest of a non-empty list of versions, returned as it was written."""
    versions = list(versions)
    if not versions:
        raise ValueError("no versions to choose from")
    best = versions[0]
    for version in versions[1:]:
        if compare(version, best) > 0:
            best = version
    return best
