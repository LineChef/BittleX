"""The pick-up drill: many puck pick-ups in one session, none of the throw, the tub or the line-up (owner, 2026-11-27).

One attempt is one trial. G2 lies at rest and says where to put the puck (claw-tip distance ahead and left, right or centred, from the SPOTS table); the owner puts it there. After a pause he stands, runs the basket goal's own retrieval
(`behavior/basket_run.retrieve`: scan, turn, last walk, close look, pick, held check, so every fix to the pick-up is shared with the basket goal), lies down holding the puck and says so. The owner takes the puck out of the claw and the
next trial starts. (Dropping it by himself, backing up and carrying on is the aim; no verified claw-release command exists yet, so the owner takes it for now.)

Scoring: retrieved (the finder saw the puck gone from the floor and the held check agreed) is a success (1.0); a pick-up that failed or a puck he could not reach or find is 0. The owner's eyes outrank the code: `g2goal verdict pickup N right|wrong`
corrects an attempt afterwards. What he learns (judged by the retrieve stage): how far short of the puck the last walk stops, and the last blind step. Nothing here calls an API.
"""
from __future__ import annotations

import time

from .approach import AttemptContext, AttemptResult, Outcome, register
from .basket import KNOBS as BASKET_KNOBS
from .basket import BasketGoal, applied
from .spec import Knob

KNOB_NAMES = ("pick_undershoot_in", "blind_step_in")
KNOBS = {n: BASKET_KNOBS[n] for n in KNOB_NAMES}
STAGE_OF = {name: v[8] for name, v in KNOBS.items()}

# (inches from the claw tip ahead, degrees to the right (+) or left (-)): the setups in order, the near middle first, then farther and nearer, then to each side. The owner puts the puck there.
SPOTS = ((8.0, 0.0), (12.0, 0.0), (6.0, 0.0), (10.0, -15.0), (10.0, 15.0), (14.0, 0.0), (8.0, -10.0), (8.0, 10.0))
PLACE_WAIT_S = 25.0               # at rest while the owner puts the puck down (and takes the last one out of the claw)

DIAGNOSIS = {
    "pick_failed": [("pick_undershoot_in", +1), ("blind_step_in", -1)],
    "could_not_reach_puck": [("blind_step_in", +1)],
    "puck_not_found": [],
}


def spot_words(spot: tuple) -> str:
    """The setup in the owner's plain terms: claw tip to the puck, then which side."""
    d, b = spot
    side = "centred" if abs(b) < 1 else ("to the right" if b > 0 else "to the left")
    return f"{d:g} inches ahead of the claw, {side}"


@register("pickup")
class PickupDrill(BasketGoal):
    name = "pickup"
    diagnosis = DIAGNOSIS
    stage_of = STAGE_OF
    ends_session = ("battery", "no_picture", "camera_stalled")           # a failed pick-up does not end the drill: the owner puts the puck down again

    def knobs(self) -> list[Knob]:
        return [Knob(name, "float", lo=lo, hi=hi, step=step, control="free", label=label, unit=unit) for name, (_m, _c, _d, lo, hi, step, label, unit, _s) in KNOBS.items()]

    def base_settings(self) -> dict:
        return {name: v[2] for name, v in KNOBS.items()}

    def _wait_for_placing(self, ctx: AttemptContext, seconds: float) -> bool:
        """Lie at rest while the puck is put down. False when a stop was asked meanwhile."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if ctx.stop():
                return False
            time.sleep(min(1.0, max(0.0, end - time.monotonic())))
        return True

    def run_attempt(self, settings: dict, ctx: AttemptContext) -> AttemptResult:
        from ..behavior import basket_run as br
        t0 = time.monotonic()
        self.attempt_no += 1
        spot = SPOTS[(self.attempt_no - 1) % len(SPOTS)]
        rec: dict = {"attempt": self.attempt_no, "time": time.strftime("%H:%M:%S"), "setup": {"ahead_in": spot[0], "bearing_deg": spot[1]}}
        if ctx.stop():
            return AttemptResult("stopped", 0.0, [], {"rec": rec})
        words = spot_words(spot)
        ctx.say(f"pick-up {self.attempt_no}: put the puck {words}")
        if ctx.announce is not None:
            ctx.announce(f"Put the puck {words}.")
        br._rest(self.env, rec)                                                          # at rest while it is put down (a no-op when he already lies)
        if not self._wait_for_placing(ctx, PLACE_WAIT_S):
            return AttemptResult("stopped", 0.0, [], {"rec": rec})
        rec["rested"] = False
        with applied(settings):
            try:
                def on_step(log, rec=rec):
                    rec["retrieval"] = {"outcome": "running", "steps": list(log)}
                r = br.retrieve(self.env, say=ctx.say, on_step=on_step, announce=ctx.announce)
                why = r["outcome"]
                rec["retrieval"] = r
            except br.Fell:
                why = "fell"
        if why == "retrieved":
            ctx.say("pick-up: the puck is in the claw (the finder says it is off the floor): lying down so it can be taken out")
            if ctx.announce is not None:
                ctx.announce("I have it. Take it out of my claw.")
        br._rest(self.env, rec)
        if self._log_path is None:
            import os
            self._log_path = os.path.join(os.path.expanduser(br.LOG_DIR), time.strftime("%Y%m%d_%H%M%S") + "_pickup_drill.json")
        self._log_attempt(rec, why, ctx)
        return AttemptResult(why or "ready", round(time.monotonic() - t0, 1), [], {"rec": rec, "settings": {k: settings.get(k) for k in KNOB_NAMES}})

    def score(self, result: AttemptResult, settings: dict) -> Outcome:
        rec = result.extra.get("rec") or {}
        ended = result.ended
        nums = {"seconds": result.seconds, "setup": rec.get("setup"), "steps": len((rec.get("retrieval") or {}).get("steps") or []), "pack_pct": None}
        if ended in ("stopped", "battery", "no_picture", "camera_stalled"):
            return Outcome("aborted", None, False, f"the drill ended as {ended}: not counted", nums)
        if ended == "fell":
            return Outcome("fell", 0.0, False, "I fell", nums)
        if ended == "retrieved":
            return Outcome("retrieved", 1.0, True, "found the puck, picked it up and the finder says it is in the claw (confirm by eye: g2goal verdict pickup N wrong if it is not)", nums, stages={"retrieve": 1.0})
        why = ended if ended in DIAGNOSIS else "puck_not_found"
        return Outcome(why, 0.0, False, f"I could not pick it up ({why.replace('_', ' ')})", nums, stages={"retrieve": 0.0})
