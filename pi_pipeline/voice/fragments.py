"""Scraps of speech that follow a false wake word (user, 2026-11-06). Half the wake triggers of a week were false (voice/wake_log.py) and what followed them was one or two filler
words: "yeah", "ah", "the", "oh", "on". Each one cost a Claude call, got a reply ("Sorry, I only caught 'on'") and was saved as a conversation record.

`is_fragment(text)` is True for a turn taken right after the wake word that holds at most two words, all of them fillers, articles, pronouns or prepositions with no content, and
that is not a local command (the caller checks that first). A greeting ("hi"), a name or any word that means something ("ball", "stop", "sit") makes it a real turn.
Only turns after the wake word are judged: "yeah" is a fine answer to a question G2 just asked. `G2_DROP_FRAGMENTS=0` turns it off."""
from __future__ import annotations

import os
import re

FILLERS = frozenset("""
a an the and or but so if as of to in on at by for with from up out off it its is are was be been am do does did have has had not no yes yeah yep nope ok okay
i me my we us you your he she him her they them this that these those there here what why how who when where which while than then just like
ah oh uh um er hm hmm huh mm mhm eh ha well right alright
""".split())


def enabled() -> bool:
    return os.environ.get("G2_DROP_FRAGMENTS", "1").strip().lower() not in ("0", "off", "false", "no")


def is_fragment(text: str) -> bool:
    words = re.findall(r"[a-z']+", (text or "").lower())
    return 0 < len(words) <= 2 and all(w in FILLERS for w in words)
