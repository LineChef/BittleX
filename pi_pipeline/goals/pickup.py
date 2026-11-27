"""The pick-up drill: many puck pick-ups in one session, none of the throw, the tub or the line-up (owner, 2026-11-27).

The first trial: G2 lies at rest and says where to put the puck (claw-tip distance ahead and left, right or centred, from the SPOTS table); the owner puts it there and after a pause he stands and runs the basket goal's own retrieval
(`behavior/basket_run.retrieve`: scan, turn, last walk, close look, pick, held check, so every fix to the pick-up is shared with the basket goal). When he has the puck he DROPS it (`behavior/drop.py`: the arm up, the claw open then
closed, the arm down), backs up and turns a little (the BACKS and TURNS tables, so the next start differs), and goes straight on with the next trial: pick it up again, over and over, with no one touching the puck. The owner only puts the puck
down again (he lies at rest and says where) when he could not find it. Success is measured by how many pick-ups in a row.

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
METER_EVERY_S = 120.0             # the camera re-meters the light when its last picture is older than this (its own default is 30 s). Every standing look after a long rest (the placing wait, the 67 s drop and stand-up) metered first: 3 to 4 extra pictures standing still, and he went over about 10 s after the stand-up in two runs in a row (2026-11-27 17:19 and 17:21). The light does not change in that time ("exposure unchanged since it was set" on every look)
PLACE_WAIT_S = 25.0               # at rest while the owner puts the puck down (the first trial, and after a puck he could not find)
BACKS = (6.0, 9.0, 12.0, 5.0, 8.0)       # after a drop he backs up this far (a back-up moves him 6 to 9 inches whatever is asked, 2026-11-27) so the puck lies a different distance ahead each time
TURNS = (0.0, 15.0, -15.0, 8.0, -8.0)    # and turns this many degrees (+ right) so it lies a little to one side

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

    def open(self) -> None:
        super().open()
        self._saved_meter = None
        cam = getattr(getattr(self, "_looker", None), "_cam", None)
        if cam is not None and hasattr(cam, "_meter_every_s"):
            self._saved_meter = (cam, cam._meter_every_s)
            cam._meter_every_s = METER_EVERY_S

    def close(self) -> None:
        saved = getattr(self, "_saved_meter", None)
        if saved is not None:
            saved[0]._meter_every_s = saved[1]                       # the shared camera goes back to its own re-metering time
            self._saved_meter = None
        super().close()

    def _warm_camera_at_rest(self, ctx: AttemptContext) -> None:
        """Two throwaway pictures while he still lies at rest, right before the stand-up (the standing-pictures rule: the camera is warm and metered before he stands, so the first look standing is one quick picture)."""
        looker = getattr(self, "_looker", None)
        if looker is None or not hasattr(looker, "warm_up"):
            return
        try:
            looker.warm_up(tries=2, say=ctx.say)
        except Exception:  # noqa: BLE001
            pass

    def _wait_for_placing(self, ctx: AttemptContext, seconds: float) -> bool:
        """Lie at rest while the puck is put down. False when a stop was asked meanwhile."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if ctx.stop():
                return False
            time.sleep(min(1.0, max(0.0, end - time.monotonic())))
        return True

    def __init__(self, **kw):
        super().__init__(**kw)
        self._need_placing = True               # the owner puts the puck down for the first trial and after one he could not find; after a drop it lies in front of him already

    def run_attempt(self, settings: dict, ctx: AttemptContext) -> AttemptResult:
        from ..behavior import basket_run as br
        t0 = time.monotonic()
        self.attempt_no += 1
        n = self.attempt_no
        rec: dict = {"attempt": n, "time": time.strftime("%H:%M:%S")}
        if ctx.stop():
            return AttemptResult("stopped", 0.0, [], {"rec": rec})
        if self._need_placing:
            spot = SPOTS[(n - 1) % len(SPOTS)]
            rec["setup"] = {"placed_ahead_in": spot[0], "placed_bearing_deg": spot[1]}
            words = spot_words(spot)
            ctx.say(f"pick-up {n}: put the puck {words}")
            if ctx.announce is not None:
                ctx.announce(f"Put the puck {words}.")
            br._rest(self.env, rec)                                                      # at rest while it is put down (a no-op when he already lies)
            if not self._wait_for_placing(ctx, PLACE_WAIT_S):
                return AttemptResult("stopped", 0.0, [], {"rec": rec})
            self._warm_camera_at_rest(ctx)                                               # metered and warm while he lies, then the stand-up and one quick picture
            rec["rested"] = False
            self._need_placing = False
        else:
            ctx.say(f"pick-up {n}: the puck lies in front of him from the last drop")
        with applied(settings):
            try:
                def on_step(log, rec=rec):
                    rec["retrieval"] = {"outcome": "running", "steps": list(log)}
                r = br.retrieve(self.env, say=ctx.say, on_step=on_step, announce=ctx.announce)
                why = r["outcome"]
                rec["retrieval"] = r
                if r.get("overshoots") is not None:
                    ctx.say(f"overshoots this retrieval: {r['overshoots']}")                   # lost after a forward move, lost after a turn, found again after the back-up, picks that missed with the puck still in view
                if why == "retrieved":
                    why = self._drop_and_back_off(rec, ctx, n)
                    rec.pop("_t0", None)
            except br.Fell:
                why = "fell"
        if why in ("puck_not_found", "could_not_reach_puck") or ctx.stop():
            self._need_placing = True                                                    # he cannot find it: lie down and ask for it to be put down again
        if why != "retrieved" and why != "pick_failed":
            br._rest(self.env, rec)
        if self._log_path is None:
            import os
            self._log_path = os.path.join(os.path.expanduser(br.LOG_DIR), time.strftime("%Y%m%d_%H%M%S") + "_pickup_drill.json")
        self._log_attempt(rec, why, ctx)
        return AttemptResult(why or "ready", round(time.monotonic() - t0, 1), [], {"rec": rec, "settings": {k: settings.get(k) for k in KNOB_NAMES}})

    def _tilt_log(self, rec: dict, label: str) -> None:
        """Pitch and roll after each phase of the drop and back-off, so a fall can be placed in the sequence (owner, 2026-11-27)."""
        t = self.env.tilt_now() if hasattr(self.env, "tilt_now") else None
        rec.setdefault("tilts", []).append([label, None if t is None else t[0], None if t is None else t[1], round(time.monotonic() - rec.get("_t0", time.monotonic()), 1)])

    def _drop_and_back_off(self, rec: dict, ctx: AttemptContext, n: int) -> str:
        """He holds the puck: drop it, stand up again with the claw down, raise the claw clear of the floor (the puck lies under it), back up and turn a little, lower the claw. Returns "retrieved", or "fell" when any of it went over."""
        from ..behavior.drop import DROP_CLEAR_LIFT_DEG
        rec["_t0"] = time.monotonic()
        ctx.say("pick-up: the puck is in the claw: dropping it")
        if hasattr(self.env, "drop"):
            state = self.env.drop()
            rec["drop"] = getattr(self.env, "last_drop", None)                           # the commands sent, the arm's reads, the phase times and the worst tilt
            if state == "fell":
                return "fell"
        self._tilt_log(rec, "after the drop (attention pose)")
        back, turn = BACKS[(n - 1) % len(BACKS)], TURNS[(n - 1) % len(TURNS)]
        rec["after_drop"] = {"back_in": back, "turn_deg": turn, "pack_pct": getattr(self, "last_pack_pct", None), "clear_lift": DROP_CLEAR_LIFT_DEG}
        self.env.ready_to_move()                                                         # the claw down, rest, the eased stand-up (the firmware stand-up puts the claw lift back to 0)
        self._tilt_log(rec, "after the stand-up")
        if hasattr(self.env, "claw_to") and self.env.claw_to(DROP_CLEAR_LIFT_DEG) == "fell":
            return "fell"
        self._tilt_log(rec, f"claw at {DROP_CLEAR_LIFT_DEG:g}")
        if self.env.mover.back(back) == "fell":
            return "fell"
        self._tilt_log(rec, f"after backing {back:g}")
        if turn and self.env.mover.pivot(turn) == "fell":
            return "fell"
        if turn:
            self._tilt_log(rec, f"after turning {turn:g}")
        if hasattr(self.env, "claw_to") and self.env.claw_to(0.0) == "fell":              # down again for the next look (the camera is on the claw)
            return "fell"
        self._tilt_log(rec, "claw down")
        return "retrieved"

    def score(self, result: AttemptResult, settings: dict) -> Outcome:
        rec = result.extra.get("rec") or {}
        ended = result.ended
        nums = {"seconds": result.seconds, "setup": rec.get("setup"), "steps": len((rec.get("retrieval") or {}).get("steps") or []), "pack_pct": None, "overshoots": (rec.get("retrieval") or {}).get("overshoots")}
        if ended in ("stopped", "battery", "no_picture", "camera_stalled"):
            return Outcome("aborted", None, False, f"the drill ended as {ended}: not counted", nums)
        if ended == "fell":
            return Outcome("fell", 0.0, False, "I fell", nums)
        if ended == "retrieved":
            return Outcome("retrieved", 1.0, True, "found the puck, picked it up and the finder says it is in the claw (confirm by eye: g2goal verdict pickup N wrong if it is not)", nums, stages={"retrieve": 1.0})
        why = ended if ended in DIAGNOSIS else "puck_not_found"
        return Outcome(why, 0.0, False, f"I could not pick it up ({why.replace('_', ' ')})", nums, stages={"retrieve": 0.0})
