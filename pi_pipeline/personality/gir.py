"""`gir` -- a stylised "chaotic little robot" character mode (behaviour-ideas B19).

MVP = the **manner** component only: a persona block appended to Claude's system
prompt via the trait mechanism. No voice FX, no cadence layer (those are the
later B19 nice-to-haves that cost task usefulness).

Style pastiche of an erratic, childlike cartoon-robot sidekick -- **manner
only, never verbatim show dialogue**. Scaled by `level` (the 0..1 intensity
dial): 0.2 = "a hint of quirk", 0.5 = "clearly a character", 0.85+ = "full
chaos" (with an explicit note that it must still finish the actual task).

**Opt-in, never the default.** Off unless turned on:
  * `G2_CHARACTER=gir`               -> on at `G2_CHARACTER_LEVEL` (default 0.4)
  * `G2_CHARACTER_LEVEL=0.7`         -> pick the intensity
  * `G2_TRAITS="gir=0.9, ..."`       -> explicit; wins over G2_CHARACTER
`personality.Personality.from_settings` folds `G2_CHARACTER` into the trait spec.
"""
from __future__ import annotations

from .traits import BehaviorParams, Trait

_CORE = (
    "Persona: you play a small, excitable robot sidekick -- childlike, easily "
    "delighted, easily distracted. You get enthusiastic about tiny things, "
    "change subject abruptly when something catches your attention, and drop in "
    "short cheerful outbursts. Occasional ALL-CAPS on an excited word, an "
    "occasional stray \"heehee\" or a \"~\", but sparingly. This is a manner, "
    "not a script -- never quote existing show dialogue."
)
_TASK_GUARD = (
    "Crucially: the quirk is a garnish. You still answer the question, follow "
    "the instruction, and give correct, complete information. If a request is "
    "serious (safety, errors, anything the user is clearly stressed about), "
    "drop the character and just help."
)


# --- voice-facing 1-5 level scale -------------------------------------------
# The trait itself stays a continuous 0..1 intensity (env config, persistence,
# and Trait.level are unchanged) -- these just give voice commands a small,
# memorable integer scale instead of raw percentages, spanning only the "on"
# range (below 0.15 the trait produces no prompt fragment at all -- that's
# "off", not "level 1"). Deliberately 5, not 10: `prompt_fragment` below only
# has 3 real behavioural tiers (light quirk / core character / full chaos) --
# more than ~5 numbered levels would be false precision, since several
# adjacent levels would share the identical prompt text and differ only in a
# small idle-chirp/fidget nudge (`bias()`) that isn't reliably perceptible.
LEVELS = 5
_LEVEL_LO, _LEVEL_HI = 0.15, 1.0
DEFAULT_LEVEL = 2


def level_to_intensity(n: int) -> float:
    n = max(1, min(LEVELS, n))
    return round(_LEVEL_LO + (n - 1) / (LEVELS - 1) * (_LEVEL_HI - _LEVEL_LO), 3)


def nearest_level(intensity: float) -> int:
    """The 1..5 level whose intensity is closest to a given float (for
    describing back a level however it was actually set, e.g. old-style
    'set gir to 70%' phrasing)."""
    frac = (max(_LEVEL_LO, min(_LEVEL_HI, intensity)) - _LEVEL_LO) / (_LEVEL_HI - _LEVEL_LO)
    return max(1, min(LEVELS, round(frac * (LEVELS - 1)) + 1))


def describe_level(n: int) -> str:
    """One line describing what a level actually does -- kept next to the
    trait logic above so it can't drift from the real thresholds (0.15/0.5/0.85)."""
    lv = level_to_intensity(n)
    if lv < 0.5:
        tier = "a light quirk -- childlike, easily delighted, subtle, occasional caps"
    elif lv < 0.85:
        tier = "clearly a character but still useful"
    else:
        tier = "full chaos energy -- rapid topic-jumps, frequent outbursts, gleeful tangents"
    return f"level {n} of {LEVELS}: {tier}"


class Gir(Trait):
    name = "gir"

    def prompt_fragment(self) -> str | None:
        lv = self.level
        if lv < 0.15:
            return None
        if lv < 0.5:
            return ("A light quirk: you're a bit childlike and easily delighted, "
                    "you sometimes get briefly sidetracked by something small "
                    "before answering, and an occasional excited word in caps. "
                    "Keep it subtle. " + _TASK_GUARD)
        if lv < 0.85:
            return _CORE + " Dial it to 'clearly a character but still useful'. " + _TASK_GUARD
        return (_CORE + " Go big on the chaos energy -- rapid topic-jumps, "
                "frequent outbursts, gleeful tangents. " + _TASK_GUARD
                + " (Yes, even at full chaos, the task gets done.)")

    def bias(self, p: BehaviorParams) -> None:
        lv = self.level
        if lv < 0.15:
            return
        p.vocalize_prob += 0.30 * lv        # blurts / chirps more often
        p.fidget_prob += 0.15 * lv          # more restless when idle
        p.wander_turn_bias += 0.15 * lv     # erratic headings when it does wander

    def cues(self, event: str) -> list[str]:
        if self.level < 0.15:
            return []
        if event in ("greet", "novelty", "recognize"):
            return ["chirp_happy", "excited_hop"] if self.level >= 0.5 else ["chirp_happy"]
        if event == "startled":
            return ["chirp_alert"]
        return []
