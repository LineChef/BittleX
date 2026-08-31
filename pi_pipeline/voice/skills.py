"""The catalogue of physical actions G2 can perform, and how each maps to an
OpenCat serial command.

OpenCat plays a named skill when it receives `k` + the skill token over serial
(e.g. `kwkF` = walk forward). Skill tokens are the built-in `InstinctBittleESP.h`
names. This module keeps a *curated, safe* subset -- not every skill in the
firmware -- exposed to the conversation layer.

`SKILLS` is the source of truth: the key is the name Claude uses (via the
perform_skill tool), the value carries the OpenCat token, a one-line description,
and whether it is a continuous gait (loops until the next command) or a one-shot
posture/gesture.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    token: str          # OpenCat skill token; serial command is "k" + token
    description: str
    continuous: bool     # True = looping gait (walk/trot); False = one-shot


SKILLS: dict[str, Skill] = {
    # gaits (continuous)
    "walk_forward":  Skill("wkF", "walk forward", True),
    "walk_left":     Skill("wkL", "walk while turning left", True),
    "walk_right":    Skill("wkR", "walk while turning right", True),
    "walk_backward": Skill("bk",  "walk backward", True),
    "trot":          Skill("trF", "trot forward (faster than walking)", True),
    "crawl":         Skill("crF", "crawl forward, body low", True),
    # postures / gestures (one-shot)
    "sit":       Skill("sit",  "sit down", False),
    "stand":     Skill("up",   "stand up in the neutral pose", False),
    "rest":      Skill("rest", "lie down and relax the servos", False),
    "balance":   Skill("balance", "stand and actively balance", False),
    "stretch":   Skill("str",  "stretch", False),
    "wave":      Skill("hi",   "wave hello with a front leg", False),
    "push_ups":  Skill("pu",   "do push-ups", False),
    "scratch":   Skill("scrh", "scratch with a hind leg", False),
    "check_around": Skill("ck", "look around, checking the surroundings", False),
    "come_here": Skill("cmh",  "beckoning / come-here gesture", False),
    "zero":      Skill("zero", "move all joints to the zero position", False),
}

# Skills the conversation layer may never trigger (calibration, factory poses,
# anything that could damage the robot or needs a human present).
_BLOCKED = {"c", "cd", "kc"}


def is_valid(name: str) -> bool:
    return name in SKILLS


def serial_command(name: str) -> str:
    """OpenCat serial command string for a skill name, e.g. 'walk_forward' -> 'kwkF'."""
    skill = SKILLS[name]
    if skill.token in _BLOCKED:
        raise ValueError(f"skill {name!r} ({skill.token}) is blocked from voice control")
    return "k" + skill.token


def catalogue_for_prompt() -> str:
    """A compact list of skill names + descriptions, for the tool schema / prompt."""
    return "\n".join(f"- {name}: {s.description}" for name, s in SKILLS.items())
