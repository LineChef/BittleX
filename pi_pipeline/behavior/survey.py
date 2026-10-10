"""Survey stops: while exploring, G2 stops at the end of a leg, looks down (the inspect bow) and up, stands again, takes one picture once the stance has settled, and walks on.

Pure logic, no I/O. `Survey` only decides *when* (the end of an exploration leg, at most once per `cooldown_s`); the two plans below are plain
timed steps `(delay_s, kind, payload, reason)` that the driver turns into Effects and plays with its choreography player:

  survey_plan   look up (`ksit`) -> look down (`kbuttUp`, the INSPECT bow) -> stand (`kup`) -> settle -> [look left, throwaway picture, look right, throwaway picture, back to the middle, settle] -> picture (the bracketed part when `looks`, the default for survey stops; `G2_SURVEY_LOOKS=0` turns it off)
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
    first_delay_s: float = 0.0      # no survey before G2 has been exploring this long (0 = the first leg's end can already be one)
    pose_settle_s: float = 1.8      # after a pose is commanded, before the picture (the skill has to finish and the body stop swaying)
    stand_settle_s: float = 2.0     # after standing again from the bow, before the picture (the stance has to settle; 2.5 s plus the 0.8 s eased stand-up ramp, 2026-10-10)
    final_settle_s: float = 1.5     # after standing again, before the walk resumes
    look_down_skill: str = "kbuttUp"
    look_up_skill: str = "ksit"
    stand_skill: str = "kup"
    looks: bool = False             # survey stops also look left and right, a throwaway picture each, then settle and take the normal picture (user, 2026-10-10); False = the one standing picture
    look_deg: float = 30.0          # how far he turns to each side (left, then right through the middle to the other side, then back to the middle)
    turn_rate_dps: tuple = (11.0, 18.0)      # measured yaw rates of the firmware left / right turn gaits (app/sinks.py WalkerSink.TURN_RATE_DPS)
    turn_gain: float = 0.85         # the walker turns a bit less than asked (WalkerSink.TURN_GAIN)
    look_pause_s: float = 0.6       # after a turn is stopped, before the picture (the picture then waits for the IMU to show he has stopped swaying)


def survey_config_from_env() -> SurveyConfig:
    """The exploration session's pacing (user, 2026-10-09: walk around more before taking a picture): a picture at most every `G2_SURVEY_COOLDOWN_S` seconds (default 60: a quarter of the old 15 s pace) and not before
    `G2_SURVEY_FIRST_S` seconds of exploring (default 30). The dataclass defaults stay as they were (15 s, no first delay) for callers that build their own config."""
    import os

    def _f(name: str, default: float) -> float:
        try:
            return max(0.0, float(os.environ.get(name, default)))
        except ValueError:
            return default
    return SurveyConfig(cooldown_s=_f("G2_SURVEY_COOLDOWN_S", 60.0), first_delay_s=_f("G2_SURVEY_FIRST_S", 30.0), looks=os.environ.get("G2_SURVEY_LOOKS", "1") != "0")     # `G2_SURVEY_LOOKS=0` = only the one standing picture


class Survey:
    def __init__(self, cfg: SurveyConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or SurveyConfig()
        self._clock = clock
        self._last = clock() - self.cfg.cooldown_s + self.cfg.first_delay_s if self.cfg.first_delay_s > 0 else float("-inf")      # the first picture waits first_delay_s

    gate = None            # optional callable(now) -> bool: also needed to be True (the interest watch: only stop for a picture when something is worth it)

    def ready(self, now: float | None = None) -> bool:
        t = self._clock() if now is None else now
        if t - self._last < self.cfg.cooldown_s:
            return False
        return True if self.gate is None else bool(self.gate(t))

    def began(self, now: float | None = None) -> None:
        self._last = self._clock() if now is None else now


def _turn_s(cfg: SurveyConfig, deg: float, right: bool) -> float:
    """How long the walker's timed firmware turn runs for `deg` degrees (the same formula as `WalkerSink.turn`)."""
    return abs(deg) * cfg.turn_gain / cfg.turn_rate_dps[1 if right else 0]


def _picture_steps(cfg: SurveyConfig, kind: str, why: str) -> tuple[list, float]:
    """The one way G2 takes a picture while exploring (user, 2026-10-10): look UP (`ksit`), look DOWN (the inspect bow), stand and settle; then, when `cfg.looks`, look LEFT and pause for a throwaway
    picture, look RIGHT and pause for a throwaway picture, come back to the middle, settle, and take the picture that counts. Pictures taken in the bow and sit poses themselves were not good, so no
    picture is taken in them. A look is a small timed turn (`("turn", radians)`, + = right) followed by a stop (`kbalance`). Returns the steps and the time of the last shot."""
    t = 0.0
    plan = [(t, "skill", cfg.look_up_skill, f"{why}: look up")]
    t += cfg.pose_settle_s
    plan.append((t, "skill", cfg.look_down_skill, f"{why}: look down, the inspect bow (the walk stops, no rest)"))
    t += cfg.pose_settle_s
    plan.append((t, "skill", cfg.stand_skill, f"{why}: stand again"))
    t += cfg.stand_settle_s
    if cfg.looks and kind == "after_bow":
        import math
        rad = math.radians(cfg.look_deg)
        for label, sign, deg in (("left", -1, cfg.look_deg), ("right", 1, 2 * cfg.look_deg), ("middle", -1, cfg.look_deg)):
            plan.append((t, "turn", sign * math.radians(deg), f"{why}: look {label}"))
            t += _turn_s(cfg, deg, sign > 0) + 0.3
            plan.append((t, "skill", "kbalance", f"{why}: stop turning, look {label}"))
            t += cfg.look_pause_s
            if label != "middle":
                plan.append((t, "shot", f"look_{label}", f"{why}: throwaway picture, looking {label}"))
        t += cfg.stand_settle_s - cfg.look_pause_s if cfg.stand_settle_s > cfg.look_pause_s else 0.0      # settle in the middle before the picture that counts
    plan.append((t, "shot", kind, f"{why}: picture, standing after looking"))
    return plan, t


def picture_pose_steps(cfg: SurveyConfig, settle_only: bool = False):
    """The pose part of the picture sequence for a caller that takes the picture itself (the voice "look"): [(delay_s, skill)] for look down, look up, stand; with settle_only=True the time (s)
    from the start at which the stance has settled and the picture can be taken."""
    plan, t = _picture_steps(cfg, "look", "voice look")
    if settle_only:
        return t
    return [(d, payload) for d, kind, payload, _why in plan if kind == "skill"]


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
