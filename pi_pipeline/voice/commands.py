"""Spoken meta-commands the voice loop handles itself, without calling Claude.

These are privacy / session controls, not conversation:

- **"forget that"** and friends  -> drop everything recorded since the wake word
  (this session's exchanges + facts). See `Memory.forget_session`.
- **"go to sleep"** -> end the follow-up window now, so the next turn needs the
  wake word again.

Matching is deliberately strict (exact phrase, or the phrase followed by
trailing speech-to-text cruft) so a normal sentence that merely contains the
word "forget" or "sleep" is never swallowed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..personality.gir import level_to_intensity as _gir_level_to_intensity

# filler words stripped before matching, so "hey G2, forget that please" ==
# "forget that"
_STRIP_TOKENS = {
    "hey", "ok", "okay", "so", "um", "uh", "please", "now", "g2", "gee", "two",
    "geetwo", "robot",
}

_APOS = re.compile(r"['’`]")
_PUNCT = re.compile(r"[^\w\s]")

_FORGET = (
    "forget that",
    "forget it",
    "forget this",
    "forget what i just said",
    "forget what i said",
    "forget that conversation",
    "forget this conversation",
    "scratch that",
    "delete that",
    "dont remember that",
    "do not remember that",
    "dont save that",
    "do not save that",
)

_SLEEP = (
    "go to sleep",
)

# Conversation mode: "let's talk" keeps G2 listening for a back-and-forth without the wake word until a quiet gap or "that's all".
# Only a short phrase counts ("lets talk", "lets talk now"): "lets talk about my day" is a normal request and goes to Claude.
_CONVERSE = ("lets talk", "let us talk", "lets chat", "let us chat", "lets have a chat", "lets have a conversation", "conversation mode")
_END_CONVERSE = ("thats all", "thats it", "were done", "we are done", "all done", "end conversation", "end the conversation",
                 "stop the conversation", "conversation over", "conversation done", "end conversation mode", "conversation mode off")
# Said to someone else while G2 was listening: he stays quiet instead of answering.
_NOT_YOU = ("not talking to you", "wasnt talking to you", "was not talking to you", "talking to someone else", "talking to somebody else",
            "not you g2", "not you buddy", "im talking to")

# Emergency stop -- a hard, latching freeze. Matched loosely (these phrases are
# never a normal request) and handled before anything else, no Claude call.
_HALT = (
    "emergency stop", "freeze", "halt", "stop stop stop", "stop moving",
    "dont move", "hold still", "abort",
)
_RESUME = (
    "resume", "you can move", "as you were", "unfreeze", "carry on",
    "at ease", "you can go", "release",
)

# 'Shut down' -- graceful: lie down first, then go dormant (NOT the emergency
# freeze, and NOT an OS power-off).
_SHUTDOWN = (
    "shut down", "shutdown", "power down", "power off", "go dormant",
    "shut yourself down", "time to shut down",
)

# Tier 1 roam -- voice-armed only ("G2, go ahead and look around").
_EXPLORE = (
    "go ahead and look around", "look around", "have a look around",
    "exploration mode", "explore", "go explore", "go and explore",
    "check things out", "go for a wander", "wander around",
)
# Restart the voice service itself ("restart your voice service"): it says so, then the service restarts and is back in about 30 s.
_RESTART_VOICE = (
    "restart your voice service", "reset your voice service", "restart the voice service", "reset the voice service", "restart voice service", "reset voice service",
    "restart your voice", "reset your voice", "restart voice", "reset voice", "reboot your voice", "reload your voice",
)

# End exploration mode entirely (the exploration session closes and the normal voice service comes back), without the emergency-stop words.
_END_EXPLORE = (
    "end exploration mode", "end explore mode", "end exploring mode", "exit exploration mode", "exit explore mode", "stop exploration mode",
    "leave exploration mode", "leave explore mode", "exploration mode off", "turn off exploration mode", "end exploration", "end exploring", "stop exploration",
    "cancel exploration", "cancel exploration mode", "cancel explore mode", "cancel exploring", "cancel explore", "cancel the exploration", "cancel exploring mode",
)
_UNEXPLORE = (
    "stop exploring", "stop looking around", "stop wandering", "come back",
    "thats enough", "that will do",
)

# "Come here" -- a directed walk toward you (distinct from "come back" above).
# No bare "come" (ambiguous with "come back"); needs "come here" / "come to me".
_COME = (
    "come here", "come to me", "over here", "here boy", "walk to me",
    "come over here",
)

# "You're unplugged" / "you're plugged in": the Pi cannot sense its charger, so the person says when it is running on battery. The Pi-battery
# warning (power/runtime_tracker.py) counts only from that moment.
_UNPLUGGED = (
    "you are unplugged", "youre unplugged", "i unplugged you", "i have unplugged you", "unplugged you",
    "you are on battery", "youre on battery", "you are running on battery", "youre running on battery",
)
_PLUGGED = (
    "you are plugged in", "youre plugged in", "i plugged you in", "i have plugged you in", "plugged you in",
    "you are charging", "youre charging", "i put you on the charger", "i put you on charge",
)

# chirps on/off -- live-toggleable, matches Features.sound_cues in spirit but
# not backed by it (that flag is boot-time only; this is a runtime override).
_CHIRPS_ON = (
    "turn on your chirps", "turn on chirps", "enable chirps", "chirps on",
    "start chirping", "enable your chirping",
)
_CHIRPS_OFF = (
    "turn off your chirps", "turn off chirps", "disable chirps", "chirps off",
    "stop chirping", "no more chirping", "quiet the chirps",
)

# narration verbosity: "narration level 4", "set verbosity to 2" -- a 1-5
# level, parsed by _parse_named_level below. Distinct wording/name from the
# mood-nudging _REBUFF list below ("be quiet" etc. nudges mood, it doesn't
# touch this setting) so the two never collide.
_NARRATION_NAMES = ("narration", "verbosity")

# character mode: "enable gir mode", "turn on gir", "gir mode off", "set gir to 70"
_CHAR_NAMES = ("gir",)
_CHAR_ON = ("enable", "turn on", "switch on", "activate", "start", "go into", "be",
            "become", "set", "make", "put")
_CHAR_OFF = ("disable", "turn off", "switch off", "deactivate", "stop", "exit",
             "leave", "quit", "cancel", "end")


# the recognizer often writes the wake word as "gee to" / "she to" when it runs into the command
_LEADING_WAKE = re.compile(r"^\s*(?:(?:(?:hey|ok|okay)\s+)?(?:gee|g|she|jee|ji|gi|jeez|key)\s+)?(?:to|too|2)\b(?=\s)")


def _normalize(text: str) -> str:
    t = _PUNCT.sub(" ", _APOS.sub("", text.lower()))
    t = _LEADING_WAKE.sub(" ", t)
    return " ".join(w for w in t.split() if w not in _STRIP_TOKENS)


# "turn off" / "shut off" are also used about other things ("turn off the music"), so only the bare forms count
_SHUTDOWN_EXACT = {"turn off", "shut off", "turn yourself off", "shut yourself off", "switch off", "switch yourself off"}


def _hit(norm: str, phrases: tuple[str, ...]) -> bool:
    return any(norm == p or norm.startswith(p + " ") for p in phrases)


@dataclass
class CharacterCommand:
    name: str            # which character, e.g. "gir"
    on: bool             # enable vs disable
    level: float | None  # requested intensity 0..1, or None to use the default


_LEVEL_WORDS = {"zero": 0.0, "quarter": 0.25, "half": 0.5, "medium": 0.5,
                "full": 1.0, "max": 1.0, "maximum": 1.0, "low": 0.25, "high": 0.85}


def _parse_named_level(raw: str, lo: int = 1, hi: int = 5) -> int | None:
    """Parse 'level N' (a small integer, 1..hi) -- the primary way to set
    gir/narration intensity now. Kept separate from _parse_level below (which
    still handles old-style 'to 70%' / 'to full' phrasing for gir) so a
    number after 'level' is never ambiguous with a raw percentage."""
    m = re.search(r"\blevel\s+(\d{1,2})\b", raw)
    if not m:
        return None
    n = int(m.group(1))
    return n if lo <= n <= hi else None


def _parse_level(raw: str) -> float | None:
    """Parse a requested intensity from raw (un-normalised) lowercased text --
    'to 0.7', 'at 70', 'to full'. Old-style percentage/word phrasing, kept
    working for gir alongside the new 'level N' scale above."""
    m = re.search(r"(?:to|at)\s+(?:(\d+(?:\.\d+)?)\s*(%|percent)?|([a-z]+))", raw)
    if not m:
        return None
    if m.group(1):
        v = float(m.group(1))
        if m.group(2) or v > 1.0:
            v /= 100.0
        return max(0.0, min(1.0, v))
    return _LEVEL_WORDS.get(m.group(3))


def _hit_short(norm: str, phrases: tuple[str, ...], extra_words: int = 2) -> bool:
    """`phrase` plus at most `extra_words` more words ("lets talk now"); a longer sentence is a different request."""
    return any(norm == p or (norm.startswith(p + " ") and len(norm.split()) - len(p.split()) <= extra_words) for p in phrases)


def addressed_elsewhere(text: str) -> bool:
    """True for "I'm not talking to you" style remarks: the person is speaking to someone else."""
    n = _normalize(text)
    return bool(n) and any(p in n for p in _NOT_YOU)


def _has_verb(norm: str, verbs: tuple[str, ...]) -> bool:
    words = set(norm.split())
    return any((" " in v and v in norm) or (" " not in v and v in words) for v in verbs)


def parse_character_command(text: str) -> CharacterCommand | None:
    """Recognise 'enable/disable <name> mode' (optionally '... level <1-5>',
    the primary form -- or the old '... to <percent/word>' phrasing, still
    understood)."""
    n = _normalize(text)
    if not n:
        return None
    raw = text.lower()
    for name in _CHAR_NAMES:
        if name not in n.split():
            continue
        named = _parse_named_level(raw, hi=5)
        level = _gir_level_to_intensity(named) if named is not None else _parse_level(raw)
        # OFF is checked first so "stop being gir" / "no more gir" win.
        if (_has_verb(n, _CHAR_OFF)
                or re.search(rf"\b{name}\b(?:\s+mode)?\s+off\b", n)
                or re.search(rf"\b(?:no|not|less)\b(?:\s+\w+)?\s+{name}\b", n)):
            return CharacterCommand(name, on=False, level=None)
        if (_has_verb(n, _CHAR_ON)
                or re.search(rf"\b{name}\b(?:\s+mode)?\s+on\b", n)
                or level is not None):            # naming a level == turn it on / adjust
            return CharacterCommand(name, on=True, level=level)
    return None


def parse_narration_command(text: str) -> int | None:
    """Recognise 'narration level <1-5>' / 'verbosity level <1-5>' /
    'set narration to <1-5>' -> the requested level, or None."""
    n = _normalize(text)
    if not n or not any(name in n.split() for name in _NARRATION_NAMES):
        return None
    return _parse_named_level(text.lower(), hi=5)
    return None


# Short reproachful phrases -> nudge the mood model to SUBDUED for a while.
# Advisory only (no command action), so a loose match is low-cost; still kept
# tight so ordinary sentences don't trip it. Phrases are already in the form
# `_normalize` produces (lowercased, no punctuation, filler words dropped).
_REBUFF = (
    "leave me alone", "stop it", "stop that", "be quiet", "shut up",
    "go away", "quit it", "cut it out", "knock it off", "stop talking",
    "thats enough", "settle down", "calm down", "youre annoying",
    "stop bothering me",
)


# Powering the Pi off is costlier to get wrong than lying down, so the OS shutdown needs a clear, short command: not a question, not a
# negation, not part of a longer sentence ("why did you shut down", "don't shut down", "tell the story about when the robot shut down").
_NOT_A_COMMAND = {"dont", "do", "not", "never", "why", "how", "what", "when", "did", "does", "was", "were", "will", "would", "could",
                  "should", "if", "because", "stop", "cant", "wont", "isnt", "arent", "no"}


def grammar_phrases() -> list[str]:
    """The short safety-critical commands (stop, shut down), bare and after the wake word, for a second, tightly
    constrained recognizer that listens alongside the full one."""
    base = [*_HALT, *_SHUTDOWN, *_SHUTDOWN_EXACT, *_END_EXPLORE]
    return base + [f"gee two {p}" for p in base]


def pick_command_hypothesis(full: str, grammar: str) -> str:
    """Choose between the full recognizer's transcript and the command-grammar recognizer's.

    The grammar result wins only when it is a clean command (no [unk]), the full transcript was not already a command,
    and the full transcript is short -- a long sentence that merely contains "shut down" stays a conversation."""
    g = (grammar or "").strip()
    if not g or "[unk]" in g or match_local_command(g) is None:
        return full
    if match_local_command(full) is not None or len(full.split()) > 6:
        return full
    return g


def is_clear_shutdown(text: str) -> bool:
    """True only for a short imperative like "shut down", "G2 shut down", "please shut yourself down", "power off"."""
    n = _normalize(text)
    words = n.split()
    return 0 < len(words) <= 5 and not (set(words) & _NOT_A_COMMAND) and not (text or "").strip().endswith("?")


def looks_like_rebuff(text: str) -> bool:
    """True for a short 'that's enough / leave me alone' style correction."""
    n = _normalize(text)
    return bool(n) and any(p in n for p in _REBUFF)


# --- the floor G2 is on: "the floor is tile", "we're on hardwood", "you are on the carpet" -> sets the label every run log records (telemetry/autolog.set_surface).
# "this is a tile floor" works too, but only WITH the word floor: plain "this is a mug" is the naming command. Local, no API call.
_SURFACES = {"hardwood": "hardwood", "hard wood": "hardwood", "wood": "hardwood", "tile": "tile", "tiles": "tile", "tiled": "tile", "carpet": "carpet",
             "carpeted": "carpet", "laminate": "laminate", "linoleum": "linoleum", "concrete": "concrete", "rug": "rug", "mat": "mat"}
_FLOOR_SET = re.compile(r"^(?:(?:the|this) floor (?:here )?(?:is|now is)|(?:were|we are|you are|youre|you are standing|g2 is|im|i am) on|set the floor to|floor is) (?:the |a )?([a-z]+(?: [a-z]+){0,2})$")
# "this is a tile floor" / "this is hardwood floor": the word floor at the end says it defines the floor (without it, "this is a ..." is the naming command, which takes a picture)
_FLOOR_THIS_IS = re.compile(r"^this is (?:the |a )?([a-z]+(?: [a-z]+){0,2}) floor$")
_FLOOR_QUERY = ("what floor am i on", "what floor are you on", "what floor is this", "which floor", "what is the floor", "whats the floor", "what surface")


def parse_floor_command(text: str) -> str | None:
    """'the floor is tile' / 'we are on the hardwood floor' / 'this is a tile floor' / 'set the floor to carpet' -> 'tile' / 'hardwood' / 'carpet'; None when it is not one."""
    n = _normalize(text)
    m = _FLOOR_SET.match(n) or _FLOOR_THIS_IS.match(n)
    if not m:
        return None
    words = [w for w in m.group(1).split() if w != "floor"]
    return _SURFACES.get(" ".join(words)) if words else None


def asks_floor(text: str) -> bool:
    n = _normalize(text)
    return any(n == q or n.startswith(q + " ") for q in _FLOOR_QUERY)


# "walk for ten seconds" (2026-10-09, user: the Claude round trip for this never seemed to work; it needs no conversation): a local command, no API call.
# Matched strictly: an optional "go / start / keep", "walk"/"walking" (optionally "forward / ahead / straight"), then optionally "for [about] N seconds / minutes".
# Number words are read before the usual filler stripping ("two" is a filler token there because of the wake word).
WALK_DEFAULT_S = 10.0
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "to": 2, "too": 2, "three": 3, "four": 4, "for": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
              "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
              "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60}
_WALK_RE = re.compile(r"^(?:(?:go|start|keep|begin) )?(?:walk|walking)(?: (?:forward|forwards|ahead|straight|straight ahead))?"
                      r"(?: (?:for )?(?:(?:about|around|like) )?(?P<num>(?:[a-z]+|\d+(?:\.\d+)?)(?: [a-z]+)?|half a) (?P<unit>seconds?|secs?|minutes?|mins?))?$")


def _walk_norm(text: str) -> str:
    t = _PUNCT.sub(" ", _APOS.sub("", text.lower()))
    t = re.sub(r"^\s*(?:(?:hey|ok|okay)\s+)?(?:g2|gee two|gee to|g two|g to|she to|gee too)\b", " ", t)
    t = _LEADING_WAKE.sub(" ", t)
    return " ".join(w for w in t.split() if w not in ("please", "now", "um", "uh", "ok", "okay", "so", "hey", "robot", "g2"))


def _words_to_number(words: str) -> float | None:
    if words == "half a":
        return 0.5
    try:
        return float(words)
    except ValueError:
        pass
    total = 0.0
    for w in words.split():
        if w not in _NUM_WORDS:
            return None
        total += _NUM_WORDS[w]
    return total or None


def parse_walk_command(text: str) -> float | None:
    """Seconds for a plain "walk (forward) [for N seconds|minutes]" request, else None. A bare "walk forward" walks WALK_DEFAULT_S. Not a walk toward someone
    ("walk to me" is come-here, matched earlier) and never backward."""
    m = _WALK_RE.match(_walk_norm(text))
    if not m:
        return None
    if not m.group("num"):
        return WALK_DEFAULT_S
    n = _words_to_number(m.group("num"))
    if n is None:
        return None
    return n * (60.0 if m.group("unit").startswith("min") else 1.0)


def match_local_command(text: str) -> str | None:
    """Return ``"halt"``, ``"resume"``, ``"shutdown"``, ``"come"``, ``"gait"``, ``"walk"``, ``"explore"``,
    ``"unexplore"``, ``"end_explore"``, ``"restart_voice"``, ``"forget"``, ``"sleep"``, ``"unplugged"``, ``"plugged"``, ``"chirps_on"``, ``"chirps_off"``,
    ``"narration_level"``, ``"character"``, ``"floor"``, ``"floor_query"``, ``"converse"``, ``"end_converse"``, or ``None``. Checked in that order
    -- an emergency stop wins over everything."""
    n = _normalize(text)
    if not n:
        return None
    if _has_verb(n, _HALT):
        return "halt"
    if _has_verb(n, _RESUME):
        return "resume"
    if _hit(n, _SHUTDOWN) or n in _SHUTDOWN_EXACT or _has_verb(n, ("shutdown",)):
        return "shutdown"
    if _hit(n, _COME):
        return "come"
    from ..gait.gait_mode import parse_gait_command
    if parse_gait_command(text) is not None:
        return "gait"                                  # "hi step" / "walk normally": before "walk" so "walk normally" is never read as a walk command
    if parse_walk_command(text) is not None:
        return "walk"
    if _hit(n, _RESTART_VOICE):
        return "restart_voice"
    if _hit(n, _END_EXPLORE):
        return "end_explore"                          # before "explore": "end exploration mode" must never arm it
    if _hit(n, _EXPLORE) or _has_verb(n, ("explore",)):
        return "explore"
    if _hit(n, _UNEXPLORE):
        return "unexplore"
    if _hit(n, _FORGET):
        return "forget"
    if _hit(n, _SLEEP):
        return "sleep"
    if _hit_short(n, _CONVERSE):
        return "converse"
    if _hit_short(n, _END_CONVERSE, extra_words=3):
        return "end_converse"
    if _hit(n, _UNPLUGGED):
        return "unplugged"
    if _hit(n, _PLUGGED):
        return "plugged"
    if _hit(n, _CHIRPS_ON):
        return "chirps_on"
    if _hit(n, _CHIRPS_OFF):
        return "chirps_off"
    if parse_narration_command(text) is not None:
        return "narration_level"
    if parse_character_command(text) is not None:
        return "character"
    if parse_floor_command(text) is not None:
        return "floor"
    if asks_floor(text):
        return "floor_query"
    return None
