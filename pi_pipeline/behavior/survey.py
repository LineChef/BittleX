"""Survey stops: while exploring, G2 stops at the end of a leg, looks down (the inspect bow) and up, stands again, takes one picture once the stance has settled, and walks on.

Pure logic, no I/O. `Survey` only decides *when* (the end of an exploration leg, at most once per `cooldown_s`); the two plans below are plain
timed steps `(delay_s, kind, payload, reason)` that the driver turns into Effects and plays with its choreography player:

  survey_plan   look down (`kbuttUp`, the INSPECT bow) -> look up (`ksit`) -> stand (`kup`) -> settle -> one picture
  naming_plan   the same, but a single look-down picture saved under a name the user gave by voice ("this is a mug"), and G2 says he will remember it

G2 does NOT lie down first (2026-10-07): a skill replaces a running learned walk without resting (`app/sinks.py`, `stop(rest=False)`), so the first step is the bow itself.
He rests only when the exploration session ends.

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
    pose_settle_s: float = 2.2      # after a pose is commanded, before the picture (the skill has to finish and the body stop swaying)
    stand_settle_s: float = 2.5     # after standing again from the bow, before the picture (the stance has to settle)
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


def _picture_steps(cfg: SurveyConfig, kind: str, why: str) -> tuple[list, float]:
    """The one way G2 takes a picture while exploring (user, 2026-10-07: the same sequence every time): look down (the inspect bow), look up (`ksit`), stand again, and take the picture once
    the stance has settled. Pictures taken in the look-down and look-up poses themselves were not good, so the picture is taken standing, after both looks. Returns the steps and the time of the shot."""
    t = 0.0
    plan = [(t, "skill", cfg.look_down_skill, f"{why}: look down, the inspect bow (the walk stops, no rest)")]
    t += cfg.pose_settle_s
    plan.append((t, "skill", cfg.look_up_skill, f"{why}: look up"))
    t += cfg.pose_settle_s
    plan.append((t, "skill", cfg.stand_skill, f"{why}: stand again"))
    t += cfg.stand_settle_s
    plan.append((t, "shot", kind, f"{why}: picture, standing after looking down and up"))
    return plan, t


def survey_plan(cfg: SurveyConfig) -> list:
    """A survey stop: bow, look up, stand, settle, one picture, then walk on."""
    plan, t = _picture_steps(cfg, "after_bow", "survey")
    t += 0.4
    plan.append((t, "diag", "survey.done", "survey: finished, walking on"))
    return plan


_NAME_OK = re.compile(r"[^a-z0-9 \-]")


def clean_name(text: str) -> str:
    """A spoken name -> a folder-safe lowercase name ('A red mug!' -> 'a red mug'); '' if nothing usable is left."""
    s = _NAME_OK.sub("", (text or "").lower()).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:40].strip()


def naming_plan(name: str, cfg: SurveyConfig) -> list:
    """Naming an object by voice takes its picture the same way as a survey stop (bow, look up, stand, settle, picture), saved under the name; he then confirms aloud and walks on."""
    plan, t = _picture_steps(cfg, f"name:{name}", f"naming {name}")
    t += 0.3
    plan.append((t, "speak", f"Okay, I will remember the {name}.", "naming: confirm"))
    t += 0.4
    plan.append((t, "diag", "naming.done", "naming: finished, walking on"))
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
