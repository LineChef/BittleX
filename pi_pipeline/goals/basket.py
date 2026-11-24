"""The basket goal: pick up the puck, throw it into the basket, look, and after a miss find it, pick it up, line up and throw again (docs/plan-detail/basket-goal-plan.md, step 6).

One attempt is one throw plus what it takes to be ready for the next (`behavior/basket_run.attempt_once`, the same function `g2basket` runs). The shared goal framework does the rest: the session loop, the judge that changes one setting at a time, the journal, the report, the overrides and the
voice start. Nothing here calls an API.

Scoring (owner, 2026-11-23): a make is the only success (1.0). A miss scores nothing, except that finding the puck and picking it up again for another attempt earns half (0.5): the attempt did the hard part of the next one. A miss that ends in "puck not found", "could not reach it", "too
near the basket" or "pick-up failed" scores 0. A fall, the battery or a camera that gave no picture is not counted. After a make the puck is in the basket and G2 is at rest, so the session ends there for the owner's reset (`Goal.target_successes` = 1).

What he learns (one setting at a time, each judged by its own stage): the throw stage judges where he throws from (`standoff_in`) and which way he aims (`aim_offset_deg`); the retrieve stage judges how far short of the puck the last walk stops (`pick_undershoot_in`) and the
blind step (`blind_step_in`); the line-up stage judges how close to right the line-up has to be before a throw (`dist_tol_in`, `align_tol_deg`). The throw's strength stays the owner's.
"""
from __future__ import annotations

import contextlib
import time

from .approach import AttemptContext, AttemptResult, Outcome, register
from .spec import Knob

# knob name: (module, constant, default, lo, hi, step, label, unit, stage)
KNOBS = {
    "standoff_in": ("basket_lineup", "TARGET_IN", 16.0, 12.0, 20.0, 1.0, "throwing from", "in", "throw"),
    "aim_offset_deg": ("basket_lineup", "AIM_OFFSET_DEG", 0.0, -6.0, 6.0, 1.0, "aiming to the right of the centre by", "deg", "throw"),
    "pick_undershoot_in": ("basket_run", "PICK_UNDERSHOOT_IN", 1.5, 0.5, 2.5, 0.5, "stopping short of the puck by", "in", "retrieve"),
    "blind_step_in": ("basket_run", "BLIND_STEP_IN", 1.5, 0.5, 3.0, 0.5, "the last blind step", "in", "retrieve"),
    "dist_tol_in": ("basket_lineup", "DIST_TOL_IN", 2.5, 1.5, 4.0, 0.5, "accepting a distance error of", "in", "lineup"),
    "align_tol_deg": ("basket_lineup", "ALIGN_TOL_DEG", 3.0, 2.0, 6.0, 1.0, "accepting an aim error of", "deg", "lineup"),
}
STAGE_OF = {name: v[8] for name, v in KNOBS.items()}

SHORT_IN = 3.0            # the puck lay this much nearer to G2 than the basket: a short throw
SIDE_DEG = 6.0            # the puck lay this far to one side of the basket's bearing: a throw off to that side
PARTIAL_RETRIEVED = 0.5   # a miss that ended with the puck picked up again for the next attempt

DIAGNOSIS = {
    "missed_short": [("standoff_in", -1)],
    "missed_long": [("standoff_in", +1)],
    "missed_left": [("aim_offset_deg", +1)],              # it landed to the left of the basket: aim further right
    "missed_right": [("aim_offset_deg", -1)],
    "missed": [("standoff_in", -1), ("aim_offset_deg", +1)],
    "pick_failed": [("pick_undershoot_in", +1), ("blind_step_in", -1)],
    "could_not_reach_puck": [("blind_step_in", +1)],
    "puck_not_found": [],
    "could_not_align": [("align_tol_deg", +1), ("dist_tol_in", +1)],
    "too_near_the_basket": [("standoff_in", +1)],
    "basket_not_found": [],
}


def _mods():
    from ..behavior import basket_lineup, basket_run
    return {"basket_lineup": basket_lineup, "basket_run": basket_run}


@contextlib.contextmanager
def env_restored(names=("G2_GYRO_BALANCE", "G2_STAND_GYRO")):
    """The throw's script run turns the gyro balance off for the whole process through the environment (`scripted_skill.play`, gyro_off); inside the voice service that must not outlive the attempt, so the values are put back (or removed) afterwards."""
    import os
    was = {n: os.environ.get(n) for n in names}
    try:
        yield
    finally:
        for n, v in was.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v


@contextlib.contextmanager
def applied(settings: dict):
    """The attempt's settings put into the behavior modules' constants and put back afterwards, however it ends (the goal never leaves a learned value behind in the running service)."""
    mods, was = _mods(), []
    try:
        for name, (mod, const, *_rest) in KNOBS.items():
            if name in settings:
                was.append((mods[mod], const, getattr(mods[mod], const)))
                setattr(mods[mod], const, float(settings[name]))
        yield
    finally:
        for m, const, val in reversed(was):
            setattr(m, const, val)


def miss_code(after: dict | None) -> str:
    """Which way a miss went, from the look after the throw: the puck's distance and bearing against the basket's (a puck beside the basket is short or long by its distance, and left or right by its bearing)."""
    if not after or not after.get("puck") or not after.get("basket"):
        return "missed"
    (pd, pb), (bd, bb) = after["puck"], after["basket"]
    if pd < bd - SHORT_IN:
        return "missed_short"
    if pd > bd + SHORT_IN:
        return "missed_long"
    if pb < bb - SIDE_DEG:
        return "missed_left"
    if pb > bb + SIDE_DEG:
        return "missed_right"
    return "missed"


@register("basket")
class BasketGoal:
    name = "basket"
    diagnosis = DIAGNOSIS
    stage_of = STAGE_OF

    def __init__(self, *, shared=None, env=None, pace=None):
        self._shared, self.env, self.pace = shared, env, pace
        self._link = None
        self._consumers: list = []
        self._looker = None
        self._own_link = False
        self.holding = False
        self.attempt_no = 0
        self._recs: list = []
        self._log_path = None
        self.last_pack_pct = None

    # ---------------------------------------------------------------------------------------------------- settings
    def knobs(self) -> list[Knob]:
        return [Knob(name, "float", lo=lo, hi=hi, step=step, control="free", label=label, unit=unit) for name, (_m, _c, _d, lo, hi, step, label, unit, _s) in KNOBS.items()]

    def base_settings(self) -> dict:
        return {name: v[2] for name, v in KNOBS.items()}

    def conditions(self) -> dict:
        return {}

    def set_user_setting(self, name: str, value) -> str:
        return f"{name} is learned by G2 on his own (a basket goal setting is not saved to a file); pin it with g2goal pin to hold it"

    # ---------------------------------------------------------------------------------------------------- hardware
    def open(self) -> None:
        if self.env is not None:
            return
        from ..behavior import ball_chase as bc
        from ..behavior import basket_run as br
        from ..behavior import chase_pace
        if self._shared is not None:                                        # inside the voice service: its link and camera stay open (as the ball goal does)
            sh = self._shared
            if sh.fan is not None:
                self._link = sh.fan.consumer()
                self._consumers.append(self._link)
            else:
                self._link = sh.link
            self._looker = br.CameraHolder(cam=sh.camera)
        else:
            from ..link.serial_link import SerialLink
            self._link = SerialLink("/dev/serial0")
            self._link.connect()
            self._own_link = True
            self._looker = br.CameraHolder()
            if not self._looker.open_port():
                raise RuntimeError("the camera did not open")
        self._looker.warm_up()
        robot = bc.SerialRobot(self._link)
        self.env = br.RealEnv(self._link, robot, self._looker, book=self.pace or chase_pace.book_for_now(save=False))

    def close(self) -> None:
        try:
            if self._link is not None:
                from ..behavior import ball_chase as bc
                bc.ensure_rest(self._link)
        except Exception:  # noqa: BLE001
            pass
        if self._shared is None and self._looker is not None:
            try:
                self._looker.close()
            except Exception:  # noqa: BLE001
                pass
        for c in self._consumers:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self._consumers = []

    def battery_ok(self, min_pct: int) -> tuple[bool, str]:
        if self._link is None:
            return True, "battery ok"
        from ..power import battery
        ok, pct, volts = battery.settled_gate(self._link, min_percent=min_pct)
        self.last_pack_pct = pct
        if pct is None:
            return ok, ("battery unreadable: continuing (testing)" if ok else "battery unreadable")
        if not ok or pct < min_pct:
            return False, f"battery {pct}% ({volts:.2f} V), below {min_pct}%"
        return True, f"battery {pct}% ({volts:.2f} V)"

    # ---------------------------------------------------------------------------------------------------- one attempt
    def run_attempt(self, settings: dict, ctx: AttemptContext) -> AttemptResult:
        from ..behavior import basket_run as br
        t0 = time.monotonic()
        self.attempt_no += 1
        rec: dict = {"attempt": self.attempt_no, "holding": self.holding, "time": time.strftime("%H:%M:%S")}
        if ctx.stop():
            return AttemptResult("stopped", 0.0, [], {"rec": rec})
        with applied(settings), env_restored():
            try:
                why, self.holding = br.attempt_once(self.env, rec, self.holding, ctx.say)
            except br.Fell:
                why = "fell"
        self._log_attempt(rec, why, ctx)
        return AttemptResult(why or "ready", round(time.monotonic() - t0, 1), [], {"rec": rec, "settings": {k: settings.get(k) for k in KNOBS}})

    def _log_attempt(self, rec: dict, why, ctx) -> None:
        """Every attempt goes to ~/g2_runs/basket_run/ as `g2basket`'s own runs do (the look's picture timing and readings, the retrieval and line-up steps, the quick-picture readings), and the look's picture timing is said once (owner, 2026-11-23: watch how late the left picture is taken)."""
        import os
        from ..behavior import basket_run as br
        pics = (rec.get("after") or {}).get("pictures") or {}
        timing = {label: r.get("t_s") for label, r in pics.items() if isinstance(r, dict)}
        if timing:
            ctx.say("look picture timing (asked, answered; seconds after the look began): " + "; ".join(f"{k} {v[0]} to {v[1]}" for k, v in timing.items() if v))
        self._recs.append(rec)
        if self._log_path is None:
            self._log_path = os.path.join(os.path.expanduser(br.LOG_DIR), time.strftime("%Y%m%d_%H%M%S") + "_basket_goal.json")
        try:
            br.write_log({"outcome": why or "running", "attempts": self._recs}, {"quick": getattr(self.env, "quick_log", [])}, path=self._log_path)
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------------------------------------------- scoring
    def score(self, result: AttemptResult, settings: dict) -> Outcome:
        rec = result.extra.get("rec") or {}
        ended = result.ended
        after = rec.get("after") or {}
        retrieval, lineup = rec.get("retrieval"), rec.get("lineup")
        nums = {"seconds": result.seconds, "after": after.get("code"), "puck": after.get("puck"), "basket": after.get("basket"),
                "retrieval": (retrieval or {}).get("outcome"), "lineup": (lineup or {}).get("outcome"), "pack_pct": (rec.get("throw") or {}).get("pack_pct")}
        if ended == "stopped":
            return Outcome("aborted", None, False, "stopped before the throw: not counted", nums)
        if ended == "battery":
            return Outcome("aborted", None, False, "the battery was too low: not counted", nums)
        if ended in ("no_picture", "throw_failed"):
            return Outcome("aborted", None, False, "the throw or its picture did not happen, so I cannot say how it went: not counted", nums)
        if ended == "fell":
            return Outcome("fell", 0.0, False, "I fell", nums)
        if ended == "made":
            return Outcome("made", 1.0, True, f"in! the puck went into the basket from {settings.get('standoff_in', 16):g} in", nums, stages={"throw": 1.0})
        code = miss_code(after) if after.get("code") == "missed" else ended
        if retrieval is None:                                                    # the throw's own result is not a miss (the basket was not seen, ...)
            if ended == "basket_not_found" or after.get("code") == "no_basket":
                return Outcome("basket_not_found", 0.0, False, "I could not see the basket after the throw", nums, stages={"throw": 0.0})
            return Outcome("aborted", None, False, f"the attempt ended as {ended}: not counted", nums)
        stages = {"throw": 0.0}
        retrieved = retrieval.get("outcome") == "retrieved"
        stages["retrieve"] = 1.0 if retrieved else 0.0
        if retrieved and lineup is not None:
            stages["lineup"] = 1.0 if lineup.get("outcome") == "aligned" else 0.0
        if retrieved:
            if lineup is not None and lineup.get("outcome") != "aligned":
                return Outcome(lineup.get("outcome") or "could_not_align", PARTIAL_RETRIEVED, False, f"I missed ({code}), found and picked up the puck, but could not line up again", nums, stages=stages)
            return Outcome(code, PARTIAL_RETRIEVED, False, f"I missed ({code.replace('missed_', '').replace('_', ' ')}), found the puck, picked it up and lined up for another throw", nums, stages=stages)
        why = retrieval.get("outcome") or "puck_not_found"
        return Outcome(why if why in DIAGNOSIS else "puck_not_found", 0.0, False, f"I missed ({code}) and then could not get the puck back ({why.replace('_', ' ')})", nums, stages=stages)
