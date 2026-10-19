"""App version. VERSION is the next release; after publishing it, set VERSION = bump(VERSION)."""

VERSION = "1.0.10"


def bump(v):
    """Next version: each part counts 0-9 and rolls into the one before it (1.0.9 -> 1.1.0, 1.9.9 -> 2.0.0)."""
    major, minor, patch = map(int, v.split("."))
    patch += 1
    if patch > 9:
        minor, patch = minor + 1, 0
    if minor > 9:
        major, minor = major + 1, 0
    return f"{major}.{minor}.{patch}"
