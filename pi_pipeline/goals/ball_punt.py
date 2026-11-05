"""The first approach (goals plan, 2026-10-31): the ball chase (behavior/ball_chase.py) as one attempt = find the ball, walk up to it, punt it once, look where it went.

Its knobs are the punt settings (behavior/punt_settings.py, with the same bounds); the user's punt_settings.json is where a goal's first session starts. Scored from the chase's trace:
how far the ball moved, how long it took, and when there was no punt, how far he got (never saw it, never got close, pushed it away, got close but never punched).
"""
from __future__ import annotations

import math
import sys
import time

from .approach import AttemptContext, AttemptResult, Outcome, register
from .spec import Knob

# name -> (step, control, label, unit). Bounds and kinds come from punt_settings.SPEC. Controls agreed with the user 2026-10-31: free unless named here.
KNOB_INFO = {
    "punt_max_in": (0.25, "free", "punching from", "in"),
    "nudge_max_in": (0.5, "free", "taking small steps closer from", "in"),
    "nudges_before_punt": (1, "free", "small steps before punching anyway", ""),
    "nudge_step_s": (0.15, "free", "one small step of", "s"),
    "nudge_gait": (None, "fixed", "small steps closer with the", "walk"),                         # the user's switch (2026-11-04): Petoi's scripted walk or the learned policy, never changed by G2
    "walk_aim_in": (0.5, "free", "ending my walks", "in from the ball"),
    "punt_align_deg": (2.0, "free", "lining up within", "deg"),
    "punch_lunge_s": (0.02, "ask", "a lunge time of", "s"),
    "punch_hold_s": (0.05, "fixed", "holding the punch for", "s"),                               # no outcome points at these four: fixed so the list matches what he can change (user, 2026-10-31)
    "lost_looks": (1, "free", "looks before I start searching:", ""),
    "back_up_s": (0.5, "fixed", "backing up for", "s"),
    "stuck_punts": (1, "fixed", "punts before I back up:", ""),
    "when_vanished": (None, "free", "when the ball vanishes up close, I", ""),
    "search_order": (None, "free", "searching by", ""),
    "search_step_deg": (5.0, "fixed", "search turns of", "deg"),
    "scan_turn_deg": (10.0, "free", "turns between claw looks of", "deg"),
    "claw_look_pan_deg": (5.0, "free", "claw looks out to", "deg"),
    "claw_look_lift_deg": (5.0, "free", "lifting the claw to", "deg for a look"),
    "align_pulse_min_s": (0.1, "free", "alignment turns of at least", "s"),
    "align_tries": (1, "free", "alignment turns before giving up:", ""),
    "when_misaligned": (None, "free", "when I can't line up, I", ""),
    "search_walk": (None, "fixed", "walking on blind after a full search circle", ""),        # only safe on a big floor: the user's call
    "max_seconds": (None, "fixed", "an attempt limit of", "s"),
    "back_up_budget_s": (None, "fixed", "backing up at most", "s an attempt"),                    # no edge detector: the user's call
    "claw_pan_sign": (None, "fixed", "the claw pan direction", ""),
    "wall_sidestep_in": (0.5, "fixed", "stepping aside from a wall by", "in"),                    # set by the sim training, adjusted by hand until an outcome points at it
    "wall_sidestep_deg": (5.0, "fixed", "turning away from a wall by", "deg"),
    "wall_sidestep_tries": (1, "fixed", "sidesteps for a ball by a wall:", ""),                       # the owner's call (2026-11-02)
    "between_moves": (None, "fixed", "between moves I wait", ""),                                    # the user's switch (2026-11-02): stand (default) or attention, never changed by G2                                # measured (claw_look --calibrate), not learned
}

# outcome code -> the knobs it points at, in order (+1 / -1 = one step up / down, "other" = another option)
DIAGNOSIS = {
    "missed": [("punt_max_in", -1), ("punt_align_deg", -1), ("nudges_before_punt", +1)],
    "missed_vanished": [("when_vanished", "other"), ("punt_max_in", -1)],
    "weak_hit": [("punt_max_in", -1), ("punt_align_deg", -1), ("punch_lunge_s", -1)],
    "never_punted": [("punt_align_deg", +1), ("nudges_before_punt", -1), ("punt_max_in", +1)],
    "pushed_away": [("walk_aim_in", +1), ("nudge_step_s", -1)],
    "never_reached": [("walk_aim_in", -1), ("nudge_max_in", +1)],
    "missed_off_line": [("punt_align_deg", -1), ("align_tries", +1)],
    "align_overshoot": [("align_pulse_min_s", -1), ("punt_align_deg", +1)],
    "align_no_move": [("align_pulse_min_s", +1)],
    "align_stuck": [("align_tries", +1), ("when_misaligned", "other"), ("punt_align_deg", +1)],
    "never_found": [("search_order", "other"), ("claw_look_lift_deg", +1), ("claw_look_pan_deg", +1), ("scan_turn_deg", -1), ("lost_looks", -1)],
}

# which stage judges each free knob (a search setting is never blamed for a missed punch)
STAGE_OF = {
    "search_order": "search", "claw_look_pan_deg": "search", "claw_look_lift_deg": "search", "scan_turn_deg": "search", "lost_looks": "search",
    "walk_aim_in": "approach", "nudge_max_in": "approach", "nudge_step_s": "approach", "nudges_before_punt": "approach",
    "punt_align_deg": "align", "align_pulse_min_s": "align", "align_tries": "align", "when_misaligned": "align",
    "punt_max_in": "punch", "when_vanished": "punch",
}
SEARCH_MOVES = ("claw_look", "search_turn", "search_back", "search_walk")

HIT_IN = 8.0                   # the ball moved at least this far: a hit
FARTHER_IN = 2.0               # the ball this much farther away in the picture after the punt: punted (user, 2026-11-01)
WEAK_IN = 3.0                  # less than this: a miss
PUSH_IN = 4.0                  # the ball farther by this much right after a walk toward it: he pushed it
VANISHED_AT_IN = 2.5           # where the ball is taken to be when it vanished at the claw


def _chase():
    from ..behavior import ball_chase
    return sys.modules[ball_chase.__name__]


def moved_in(before: tuple, after: dict) -> float:
    """How far the ball moved, from (distance, bearing) before the punt and the reading after (law of cosines)."""
    d0, b0 = before
    d1, b1 = after["distance_in"], after["bearing_deg"]
    return math.sqrt(max(0.0, d0 * d0 + d1 * d1 - 2 * d0 * d1 * math.cos(math.radians(b1 - b0))))


def align_stats(trace: list) -> dict:
    """The fine-alignment pulses and what the next picture showed: overshoots (the ball swung past straight to the other side) and pulses that did not move him."""
    pulses = overshoots = no_moves = 0
    before = None
    pending = False
    for e in trace:
        if e.get("kind") == "look":
            b = e.get("ball")
            if pending and before is not None and b is not None:
                if (before > 0) != (b["bearing_deg"] > 0) and abs(b["bearing_deg"]) > 3:
                    overshoots += 1
                elif abs(b["bearing_deg"] - before) < 1.5:
                    no_moves += 1
            pending = False
            before = b["bearing_deg"] if b is not None else None
        elif e.get("kind") == "act" and e.get("act") == "align":
            pulses += 1
            pending = True
    return {"align_pulses": pulses, "align_overshoots": overshoots, "align_no_moves": no_moves}


def _fmt_s(x: float) -> str:
    return f"{x:.0f} s"


@register("ball_punt")
class BallPunt:
    name = "ball_punt"
    diagnosis = DIAGNOSIS
    stage_of = STAGE_OF

    def __init__(self, *, robot=None, camera=None, saver=None, link=None, pace=None, wall_check=None):
        self.robot, self.camera, self.saver, self._link, self.pace = robot, camera, saver, link, pace
        self._cam = None
        self.last_pack_pct = None                                           # the pack % read before the last attempt (kept with every attempt, not learned from yet)
        self.wall_check = wall_check

    # ---------------------------------------------------------------------------------------------------- settings
    def knobs(self) -> list[Knob]:
        from ..behavior import punt_settings as ps
        out = []
        for name, (_const, kind, lo, hi, _doc) in ps.SPEC.items():
            step, control, label, unit = KNOB_INFO.get(name, (None, "free", "", ""))
            if kind is str:
                out.append(Knob(name, "choice", options=tuple(lo), control=control, label=label, unit=unit))
            elif kind is bool:
                out.append(Knob(name, "bool", control=control, label=label, unit=unit))
            else:
                out.append(Knob(name, "int" if kind is int else "float", lo=lo, hi=hi, step=step, control=control, label=label, unit=unit))
        return out

    def base_settings(self) -> dict:
        from ..behavior import punt_settings as ps
        eff, _problems = ps.effective(_chase())
        return eff

    def conditions(self) -> dict:
        return {}

    def set_user_setting(self, name: str, value) -> str:
        """The user confirmed a suggestion: write it into their own punt settings file (checked like any change)."""
        from ..behavior import punt_settings as ps
        return ps.set_value(_chase(), name, str(value).lower() if isinstance(value, bool) else str(value))

    # ---------------------------------------------------------------------------------------------------- hardware
    def open(self) -> None:
        if self.robot is not None:
            return
        from ..behavior import ball_chase as bc
        from ..config import settings
        from ..link.serial_link import SerialLink
        from ..vision.snapshot import CameraSnapshotter
        self._link = SerialLink("/dev/serial0")
        self._link.connect()
        self._cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump)     # exposure balancing stays on
        self.camera = bc._SnapshotCamera(self._cam)
        import threading
        threading.Timer(1.8, self.camera.premeter, kwargs={"force": True}).start()        # meter the light while he is standing up (the stand-up is 4 s of waiting anyway), not at the first picture
        bc._stand_if_lying(self._link)
        self.robot = bc.SerialRobot(self._link)
        self.saver = bc.PictureSaver("~/.local/share/g2/explore_pictures/named/greenball")
        if self.pace is None:
            from ..behavior.chase_pace import book_for_now
            self.pace = book_for_now()                                       # G2's own measured pace and turn rates, per attachment and floor
        if self.wall_check is None:
            from .walls import make_wall_check
            self.wall_check = make_wall_check()                              # walls rank above the punt; None without a wall calibration from this hardware

    def close(self) -> None:
        if self._link is None:
            return
        try:
            if self.robot is not None and callable(getattr(self.robot, "claw_pose", None)):
                self.robot.claw_pose(0.0, 0.0)
        finally:
            if self._cam is not None:
                self._cam.close()
            self._link.send("krest", read_reply=False, settle=0.0)          # rest at the end of the session
            time.sleep(2.5)

    def battery_ok(self, min_pct: int) -> tuple[bool, str]:
        if self._link is None:
            ok = self.robot.battery_ok() if self.robot is not None else True
            return ok, "battery ok" if ok else "battery low"
        from ..power import battery
        ok, pct, volts = battery.motion_gate(self._link)
        self.last_pack_pct = pct
        if pct is None:
            return ok, ("battery unreadable: continuing (testing)" if ok else "battery unreadable")
        if not ok or pct < min_pct:
            return False, f"battery {pct}% ({volts:.2f} V), below {min_pct}%"
        return True, f"battery {pct}% ({volts:.2f} V)"

    # ---------------------------------------------------------------------------------------------------- one attempt
    def run_attempt(self, settings: dict, ctx: AttemptContext) -> AttemptResult:
        from ..behavior import punt_settings as ps
        chase = _chase()
        ps.apply(chase, {k: v for k, v in settings.items() if k in ps.SPEC})
        planner = chase.ChasePlanner()
        trace: list = []
        from .standing import apply as apply_standing, learn as learn_standing
        walls_used = apply_standing("walls")                                 # the walls goal's current values (its chase_wall_in and turn) for this attempt
        t0 = time.monotonic()
        ended = chase.run_chase(self.robot, self.camera, ctx.stop, planner=planner, saver=self.saver, announce=ctx.announce, max_punts=1,
                                max_seconds=float(settings.get("max_seconds", chase.DEFAULT_MAX_SECONDS if hasattr(chase, "DEFAULT_MAX_SECONDS") else 75.0)),
                                trace=trace, after_punt_look=True, say=ctx.say, pace=self.pace, wall_check=self.wall_check, battery_checked=True)
        from .walls import events_from_trace
        learn_standing("walls", events_from_trace(trace), "ball chase", used=walls_used)
        extra = {"punt_log": list(planner.punt_log), "walk_log": list(planner.walk_log), "back_s": round(planner.back_s, 1)}
        if self.pace is not None:
            extra["pace"] = self.pace.snapshot()
        return AttemptResult(ended, round(time.monotonic() - t0, 1), trace, extra)

    # ---------------------------------------------------------------------------------------------------- scoring
    def score(self, result: AttemptResult, settings: dict) -> Outcome:
        o = self._score(result, settings)
        if o.counted:
            o.stages = self.stages(result, settings, o)
        return o

    def stages(self, result: AttemptResult, settings: dict, o: Outcome) -> dict:
        """A score per stage the attempt reached. search: only when he had to search (or never found it), 1 = found at once, 0.5 = at half the time limit, 0 = never;
        approach: once found, 1 = got close (minus 0.4 for pushing it away), 0 = never got close; align: once close, 1 = punched lined up, 0 = could not line up or punched
        off line; punch: once punted, the outcome's score."""
        tr = result.trace
        nums = o.numbers
        max_s = float(settings.get("max_seconds", 75.0)) or 75.0
        out = {}
        first = nums.get("first_seen_s")
        searched = False
        for e in tr:
            if e.get("kind") == "claw_seen" and not e.get("after_punt"):
                searched = True                                                 # found by a claw look: that look was the search (it is written before its own "act" line)
                break
            if e.get("kind") == "look" and e.get("ball"):
                break
            if e.get("kind") == "act" and e.get("act") in SEARCH_MOVES:
                searched = True
                break
        punted = result.ended == "punted"
        if first is None and not punted:                                       # never saw it (a punt always means he found it, even with no sighting in the trace)
            out["search"] = 0.0
            return out
        if searched and first is not None:
            out["search"] = round(max(0.0, 1.0 - float(first) / max_s), 3)
        close = punted or (nums.get("closest_in") is not None and nums["closest_in"] <= float(settings.get("nudge_max_in", _chase().NUDGE_MAX_IN)))
        out["approach"] = (1.0 - (0.4 if nums.get("pushes") else 0.0)) if close else 0.0
        if close:
            tol = float(settings.get("punt_align_deg", 12.0))
            if punted:
                b = nums.get("punt_bearing_deg")
                out["align"] = 1.0 if (b is None or abs(b) <= tol) else 0.0
            else:
                out["align"] = 0.0 if o.code.startswith("align") or o.code == "never_punted" else 0.5
        if punted:
            out["punch"] = float(o.score)
        return out

    def _score(self, result: AttemptResult, settings: dict) -> Outcome:
        tr = result.trace
        max_s = float(settings.get("max_seconds", 75.0)) or 75.0
        tfrac = min(1.0, result.seconds / max_s)
        looks = [e for e in tr if e.get("kind") == "look"]
        claws = [e for e in tr if e.get("kind") == "claw_seen" and not e.get("after_punt")]          # a look for where the ball went after the punt is not a search
        seen = [e["ball"] for e in looks if e.get("ball")] + [{"distance_in": e["distance_in"]} for e in claws]
        firsts = [e for e in tr if (e.get("kind") == "look" and e.get("ball")) or (e.get("kind") == "claw_seen" and not e.get("after_punt"))]
        first_seen = next((e.get("t", 0.0) for e in firsts), None)
        found_by = None
        if firsts:
            found_by = "claw look" if firsts[0].get("kind") == "claw_seen" else "straight look"
        nums = {"seconds": result.seconds, "first_seen_s": first_seen, "found_by": found_by, "looks": len(looks),
                "claw_looks": sum(1 for e in tr if e.get("kind") == "claw_look" and not e.get("after_punt")), "backed_up_s": result.extra.get("back_s", 0.0),
                "walks": sum(1 for e in tr if e.get("kind") == "act" and e.get("act") == "walk"), **align_stats(tr)}
        if result.ended == "fell":
            return Outcome("fell", 0.0, False, f"I fell after {_fmt_s(result.seconds)}", nums)
        if result.ended == "ball_by_wall":
            return Outcome("ball_by_wall", None, False, "the ball was too close to a wall, so I left it (walls come first): not counted", nums)
        if result.ended not in ("punted", "time"):
            return Outcome("aborted", None, False, f"the attempt ended early ({result.ended}): not counted", nums)
        if result.ended == "punted":
            punt = next((e for e in reversed(tr) if e.get("kind") == "act" and e.get("act") == "punt"), {})
            at = punt.get("at")
            vanished = not at or at[0] is None
            before = (VANISHED_AT_IN, 0.0) if vanished else (float(at[0]), float(at[1]))
            after_e = next((e for e in reversed(tr) if e.get("kind") == "after_punt"), {})
            after = after_e.get("ball")
            nums.update(punt_at_in=None if vanished else before[0], punt_bearing_deg=None if vanished else before[1], vanished=vanished)
            where = "at the claw (out of sight)" if vanished else f"from {before[0]:.1f} in"
            if after is None and after_e and after_e.get("picture") is False:
                return Outcome("punt_unseen_camera", None, False, f"I punched {where} but the camera gave no picture afterwards: not counted", nums)
            if after is None:
                nums["moved_in"] = None
                return Outcome("hit_unseen", round(0.6 - 0.15 * tfrac, 3), True, f"I punched {where} and the ball went out of sight ({_fmt_s(result.seconds)})", nums)
            mv = moved_in(before, after)
            nums["moved_in"] = round(mv, 1)
            farther = float(after["distance_in"]) - before[0]
            if farther >= FARTHER_IN:                          # no longer in front of the claw: punted away (user, 2026-11-01)
                return Outcome("hit", round(0.75 + 0.25 * min(1.0, mv / 24.0) - 0.15 * tfrac, 3), True, f"I punched {where} and the ball went {mv:.0f} in, {farther:.0f} in farther away ({_fmt_s(result.seconds)})", nums)
            if mv >= HIT_IN:
                return Outcome("hit", round(0.75 + 0.25 * min(1.0, mv / 24.0) - 0.15 * tfrac, 3), True, f"I punched {where} and the ball went {mv:.0f} in ({_fmt_s(result.seconds)})", nums)
            if mv >= WEAK_IN:
                return Outcome("weak_hit", 0.4, False, f"I punched {where} but the ball only went {mv:.0f} in", nums)
            if not vanished and abs(before[1]) > 0.6 * float(settings.get("punt_align_deg", 12.0)):
                return Outcome("missed_off_line", 0.2, False, f"I punched {where}, {before[1]:+.0f} deg off straight, and missed: the ball moved {mv:.0f} in", nums)
            return Outcome("missed_vanished" if vanished else "missed", 0.2, False, f"I punched {where} and missed: the ball moved {mv:.0f} in", nums)
        # time ran out with no punt
        if not seen:
            return Outcome("never_found", 0.0, False, f"I never saw the ball in {_fmt_s(result.seconds)}", nums)
        closest = min(b["distance_in"] for b in seen)
        nums["closest_in"] = round(closest, 1)
        pushes = 0
        last_d = None
        walked = False
        for e in tr:
            if e.get("kind") == "look":
                b = e.get("ball")
                if b is not None:
                    if walked and last_d is not None and b["distance_in"] > last_d + PUSH_IN:
                        pushes += 1
                    last_d = b["distance_in"]
                walked = False
            elif e.get("kind") == "act" and e.get("act") == "walk":
                walked = True
        nums["pushes"] = pushes
        if pushes:
            return Outcome("pushed_away", 0.1, False, f"I pushed the ball away {pushes} time(s) while walking up to it and never punched", nums)
        chase = _chase()
        if nums["align_pulses"] >= 2:
            if nums["align_overshoots"] >= 2:
                return Outcome("align_overshoot", 0.15, False, f"I kept turning past the ball while lining up ({nums['align_overshoots']} times in {nums['align_pulses']} small turns)", nums)
            if nums["align_no_moves"] >= 2:
                return Outcome("align_no_move", 0.15, False, f"my small turns did not move me ({nums['align_no_moves']} of {nums['align_pulses']})", nums)
            if closest <= float(settings.get("nudge_max_in", chase.NUDGE_MAX_IN)):
                return Outcome("align_stuck", 0.15, False, f"I got within {closest:.0f} in but could not line up in {nums['align_pulses']} small turns", nums)
        if closest <= float(settings.get("nudge_max_in", chase.NUDGE_MAX_IN)):
            return Outcome("never_punted", 0.15, False, f"I got within {closest:.0f} in but never punched", nums)
        return Outcome("never_reached", 0.1, False, f"I saw the ball but never got closer than {closest:.0f} in", nums)
