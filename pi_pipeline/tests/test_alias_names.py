"""tools/g2_aliases.sh: every g2* helper is defined once (2026-11-17: a second g2mem silently hid the first for weeks)."""
import collections
import os
import re

_ALIASES = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "g2_aliases.sh")


def _definitions() -> list[str]:
    with open(_ALIASES) as f:
        text = f.read()
    return re.findall(r"^(g2[A-Za-z0-9_]*)\(\)", text, flags=re.M)


def test_no_helper_is_defined_twice():
    dup = sorted(n for n, c in collections.Counter(_definitions()).items() if c > 1)
    assert dup == [], f"defined more than once (the later one hides the earlier): {dup}"


def test_the_memory_helpers_are_the_two_distinct_ones():
    names = set(_definitions())
    assert {"g2mem", "g2memory", "g2pimem", "g2membackup"} <= names                           # g2mem = the Pi's RAM log, g2memory = the Mac's copy of G2's memory
