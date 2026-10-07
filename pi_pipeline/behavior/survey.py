"""Survey stops: while exploring, G2 stops at the end of a leg, looks down and up, takes one picture in each pose, and walks on.

Pure logic, no I/O. `Survey` only decides *when* (the end of an exploration leg, at most once per `cooldown_s`); the two plans below are plain
timed steps `(delay_s, kind, payload, reason)` that the driver turns into Effects and plays with its choreography player:

  survey_plan   stop -> stand -> look down (`kbuttUp`, nose-down bow: the INSPECT pose) -> picture -> look up (`ksit`, chest raised) -> picture -> stand
  naming_plan   the same, but a single look-down picture saved under a name the user gave by voice ("this is a mug"), and G2 says he will remember it

Taking a picture is a camera call over USB: no network, no API call. How the pictures are saved and processed: `vision/exploration_pictures.py`,
`tools/curate_exploration.py`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass


@dataclass
class SurveyConfig:
    cooldown_s: float = 15.0        # at most one survey this often (the end of every leg is a chance, not a promise)
    stand_s: float = 1.2            # after the walk stops, before standing up
    stand_settle_s: float = 1.8     # standing up takes this long
    pose_settle_s: float = 2.2      # after a pose is commanded, before the picture (the skill has to finish and the body stop swaying)
    final_settle_s: float = 1.5     # after standing again, before the walk resumes
    look_down_skill: str = "kbuttUp"
    look_up_skill: str = "ksit"
    stand_skill: str = "kup"


class Survey:
    def __init__(self, cfg: SurveyConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or SurveyConfig()
        self._clock = clock
        self._last = float("-inf")

    def ready(self, now: float | None = None) -> bool:
        t = self._clock() if now is None else now
        return t - self._last >= self.cfg.cooldown_s

    def began(self, now: float | None = None) -> None:
        self._last = self._clock() if now is None else now


def survey_plan(cfg: SurveyConfig) -> list:
    t = 0.0
    plan = [(t, "stop", None, "survey: stop walking")]
    t += cfg.stand_s
    plan.append((t, "skill", cfg.stand_skill, "survey: stand"))
    t += cfg.stand_settle_s
    plan.append((t, "skill", cfg.look_down_skill, "survey: look down"))
    t += cfg.pose_settle_s
    plan.append((t, "shot", "look_down", "survey: picture, looking down"))
    t += 0.4
    plan.append((t, "skill", cfg.look_up_skill, "survey: look up"))
    t += cfg.pose_settle_s
    plan.append((t, "shot", "look_up", "survey: picture, looking up"))
    t += 0.4
    plan.append((t, "skill", cfg.stand_skill, "survey: stand again"))
    t += cfg.final_settle_s
    plan.append((t, "diag", "survey.done", "survey: finished, walking on"))
    return plan


_NAME_OK = re.compile(r"[^a-z0-9 \-]")


def clean_name(text: str) -> str:
    """A spoken name -> a folder-safe lowercase name ('A red mug!' -> 'a red mug'); '' if nothing usable is left."""
    s = _NAME_OK.sub("", (text or "").lower()).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:40].strip()


def naming_plan(name: str, cfg: SurveyConfig) -> list:
    t = 0.0
    plan = [(t, "stop", None, f"naming {name}: stop walking")]
    t += cfg.stand_s
    plan.append((t, "skill", cfg.stand_skill, "naming: stand"))
    t += cfg.stand_settle_s
    plan.append((t, "skill", cfg.look_down_skill, "naming: look down at it"))
    t += cfg.pose_settle_s
    plan.append((t, "shot", f"name:{name}", f"naming: picture of the {name}"))
    t += 0.3
    plan.append((t, "speak", f"Okay, I will remember the {name}.", "naming: confirm"))
    t += 0.4
    plan.append((t, "skill", cfg.stand_skill, "naming: stand again"))
    t += cfg.final_settle_s
    plan.append((t, "diag", "naming.done", f"naming: finished, walking on"))
    return plan


# What people say to name an object: "this is a mug", "this is my red mug", "remember this as the mug", "that's a mug", "call this the mug".
_NAMING = re.compile(
    r"^(?:(?:okay|ok|hey|g2)[ ,]+)*"
    r"(?:(?:this|that|it)(?:'s| is)|remember (?:this|that|it) as|call (?:this|that|it)|this one is)\s+"
    r"(?:a |an |the |my |our )?(?P<name>[a-z][a-z0-9 \-]{1,38})$")


def parse_naming(text: str) -> str:
    """The object name in a naming sentence, or '' if the sentence is not one."""
    s = re.sub(r"[.!?,]", "", (text or "").lower()).strip()
    m = _NAMING.match(s)
    return clean_name(m.group("name")) if m else ""
