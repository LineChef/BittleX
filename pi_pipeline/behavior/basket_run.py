"""The full basket sequence, as one process on one serial connection (the basket goal, docs/plan-detail/basket-goal-plan.md, steps 3 to 5; owner, 2026-11-23).

Per attempt: stand, pick the puck up, take the grip picture, throw (the lob: `behavior/lob.py` through `scripted_skill.play`); then LOOK (the shared claw look, from the attention pose, one picture read by the basket and puck finders) and classify the throw
(`goals/basket_outcome.classify_throw`). The puck seen on the floor outside the basket is a miss: he searches for it (pivot scan), walks to it (the line-up's movers, the pace book's paces), walks the last inches and picks it up with `pickF`, checks by a look that it is gone from the floor,
lines up on the basket again (`basket_lineup.lineup`: quick pictures with the claw down) and throws the next attempt without a pick-up (he already holds it). The puck not seen anywhere is a make or a lost puck and the run stops for the owner to reset it, as the plan says.
Stops: 5 attempts, a fall, a battery gate that fails, a basket never found, a puck never found or reached, three failed pick-ups, and never closer than the line-up's buffer to the basket. Every stage is logged to `~/g2_runs/basket_run/` for the report.

`next_retrieval_action` and `run_sequence` are pure (the robot, the camera and the throw are handed in as an `Env`), tested on a simulated floor; `RealEnv` wires them to G2 and is only used by `main`. UNPROVEN on G2: the first run is watched by the owner (a separate process, `g2basket`).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from . import basket_lineup as bl
from ..goals import basket_outcome as bo
from ..vision.object_finder import ObjectReading

MAX_ATTEMPTS = 5
MAX_RETRIEVAL_STEPS = 16
PICK_TRIES = 3
SCAN_STEP_DEG, SCAN_MAX_DEG = 27.0, 360.0
ALIGN_DEG = 6.0                      # the puck's bearing must be inside this before the last walk (a pick-up window is about 1 inch wide)
PICK_STAND_IN = 7.0                  # nearer than this and centred, he makes the last walk and picks up
APPROACH_TOL_IN = 1.5
APPROACH_STEP_MAX_IN = 10.0
PICK_UNDERSHOOT_IN = 0.5             # the last walk stops this short of the finder's distance: the puck must be at the claw tip, and a puck pushed away is lost
BASKET_GUARD_IN = bl.BUFFER_IN + bl.CLOSE_MARGIN_IN
GONE_WITHIN_IN = 12.0                # after a pick-up a puck still seen on the floor this near means the pick-up missed
LOG_DIR = "~/g2_runs/basket_run"
BURST_S = 6.0                        # the picture burst after the throw is sent: the throw (about 1.2 s), the flight, the landing, the bounce and the settle


@dataclass
class RAction:
    kind: str                        # "scan" | "pivot" | "nudge" | "forward" | "pick" | "give_up"
    value: float = 0.0               # degrees (scan, pivot, nudge; + right) or inches (forward, pick: the last walk)
    why: str = ""


@dataclass
class RState:
    scanned_deg: float = 0.0
    steps: int = 0
    picks: int = 0
    log: list = field(default_factory=list)


def next_retrieval_action(puck, basket, st: RState) -> RAction:
    """The next step toward the puck from a fresh look (a PuckReading or None, and the basket reading or None in the same picture)."""
    if st.steps >= MAX_RETRIEVAL_STEPS:
        return RAction("give_up", 0.0, "could_not_reach_puck")
    if basket is not None and basket.claw_in < BASKET_GUARD_IN:
        return RAction("give_up", 0.0, "too_near_the_basket")
    if puck is None:
        if st.scanned_deg >= SCAN_MAX_DEG:
            return RAction("give_up", 0.0, "puck_not_found")
        st.scanned_deg += SCAN_STEP_DEG
        st.steps += 1
        return RAction("scan", SCAN_STEP_DEG, "puck not in view: pivot scan")
    st.scanned_deg = 0.0
    d, b = float(puck.claw_in), float(puck.bearing_deg)
    if abs(b) >= bl.PIVOT_MIN_DEG:
        st.steps += 1
        return RAction("pivot", bl._pivot_for(b), "puck far off to the side: pivot toward it")
    if abs(b) > ALIGN_DEG:
        st.steps += 1
        return RAction("nudge", b, "small turn onto the puck")
    if d > PICK_STAND_IN + APPROACH_TOL_IN:
        st.steps += 1
        return RAction("forward", min(APPROACH_STEP_MAX_IN, d - PICK_STAND_IN), "walk up to the puck")
    return RAction("pick", max(0.0, d - PICK_UNDERSHOOT_IN), "centred and close: the last walk, then the pick-up")


def _box(reading, name: str) -> ObjectReading | None:
    """The finders' readings as the outcome classifier's ObjectReading (it works on the blobs' boxes)."""
    if reading is None:
        return None
    w, h = float(reading.width_px), float(reading.height_px)
    left, top = int(reading.x - w / 2), int(reading.y - h / 2)
    return ObjectReading(name, reading.x, reading.y, left, int(left + w - 1), top, int(top + h - 1), int(getattr(reading, "area", w * h)), int(w), float(reading.claw_in), reading.bearing_deg, bool(getattr(reading, "touches_edge", False)))


def classify_after(basket, puck) -> tuple[str, str]:
    """(code, plain words) for one throw from the look afterwards. The puck on the floor with no basket in the picture is still a miss (it is not in a basket)."""
    if basket is None and puck is not None:
        return bo.MISSED, "The puck is on the floor and the basket is not in the picture: a miss."
    return bo.classify_throw(_box(basket, "basket"), _box(puck, "cylinder"))


class Fell(Exception):
    pass


class BurstRecorder:
    """The picture record of one throw (owner, 2026-11-23: see the puck leave the claw, its path, and the bounce or the miss). `start(t_send)` runs the camera's back-to-back burst in a thread; `join()` waits and saves the frames to `out_dir`, each
    named with the time its request and its arrival fell after the throw was sent. A diagnostic only: nothing reads the frames during the run, and a failure here never stops the throw."""

    def __init__(self, cam, out_dir: str, seconds: float = BURST_S, clock=time.monotonic):
        self.cam, self.out_dir, self.seconds, self._clock = cam, out_dir, seconds, clock
        self.thread = None
        self.t_send = None
        self.saved: list = []

    def start(self, t_send: float | None = None) -> None:
        import threading
        self.t_send = t_send if t_send is not None else self._clock()
        self.thread = threading.Thread(target=self._run, name="burst", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            frames = self.cam.grab_burst(self.seconds)
            os.makedirs(self.out_dir, exist_ok=True)
            for i, (t_req, t_got, jpeg) in enumerate(frames):
                name = f"f{i:02d}_req{t_req - self.t_send:+.2f}_got{t_got - self.t_send:+.2f}.jpg"
                with open(os.path.join(self.out_dir, name), "wb") as f:
                    f.write(jpeg)
                self.saved.append(name)
        except Exception:  # noqa: BLE001
            pass

    def join(self, timeout: float = 15.0) -> list:
        if self.thread is not None:
            self.thread.join(timeout)
        return self.saved


def merge_looks(seen: dict, offsets: dict):
    """One (basket, puck) from the claw look's pictures. `seen`: label to (basket reading or None, puck reading or None) in picture bearings; `offsets`: label to where that picture points, in degrees from straight ahead (+ right).
    The basket comes from the centre picture first, else the first other one; the puck is the nearest seen in any picture. Bearings are returned in the body frame (the picture's bearing plus its offset)."""
    from dataclasses import replace
    baskets, pucks = [], []
    for label, (basket, puck) in seen.items():
        off = offsets.get(label, 0.0)
        if basket is not None:
            baskets.append((0 if label == "centre" else 1, replace(basket, bearing_deg=basket.bearing_deg + off)))
        if puck is not None:
            pucks.append((puck.claw_in, replace(puck, bearing_deg=puck.bearing_deg + off)))
    basket = min(baskets, key=lambda t: t[0])[1] if baskets else None
    puck = min(pucks, key=lambda t: t[0])[1] if pucks else None
    return basket, puck


def retrieve(env, say=print) -> dict:
    """Search for the puck, walk to it and pick it up. Returns {"outcome": "retrieved" | a give-up reason | "fell", "steps": [...]}."""
    st = RState()
    while True:
        try:
            basket, puck = env.look()
        except Fell:
            return {"outcome": "fell", "steps": st.log}
        act = next_retrieval_action(puck, basket, st)
        st.log.append({"action": act.kind, "value": round(act.value, 1), "why": act.why, "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1)),
                       "basket_in": None if basket is None else round(basket.claw_in, 1)})
        say(f"retrieve: {act.why}" + (f" ({act.kind} {act.value:.1f})" if act.kind != "give_up" else ""))
        if act.kind == "give_up":
            return {"outcome": act.why, "steps": st.log}
        if act.kind == "pick":
            state = env.mover.forward(act.value) if act.value >= 0.5 else "ok"
            if state == "fell":
                return {"outcome": "fell", "steps": st.log}
            got = env.pick()
            st.picks += 1
            if got == "fell":
                return {"outcome": "fell", "steps": st.log}
            try:
                _b, still = env.look()
            except Fell:
                return {"outcome": "fell", "steps": st.log}
            gone = still is None or still.claw_in > GONE_WITHIN_IN
            st.log.append({"action": "picked_check", "value": 0.0, "why": "puck gone from the floor" if gone else "puck still on the floor", "puck": None if still is None else (round(still.claw_in, 1), round(still.bearing_deg, 1))})
            if gone:
                return {"outcome": "retrieved", "steps": st.log}
            if st.picks >= PICK_TRIES:
                return {"outcome": "pick_failed", "steps": st.log}
            continue
        result = getattr(env.mover, {"scan": "scan", "pivot": "pivot", "nudge": "nudge", "forward": "forward"}[act.kind])(act.value)
        if result == "fell":
            return {"outcome": "fell", "steps": st.log}


def run_sequence(env, max_attempts: int = MAX_ATTEMPTS, say=print) -> dict:
    """The attempts. Returns {"outcome": ..., "attempts": [...]}; the outcome says why it stopped: "made_or_lost" (stop for the owner's reset), "max_attempts", "fell", "battery", "throw_failed",
    "basket_not_found", "could_not_align", "puck_not_found", "could_not_reach_puck", "too_near_the_basket", "pick_failed"."""
    attempts: list = []
    holding = False
    outcome = "max_attempts"
    for n in range(1, max_attempts + 1):
        rec: dict = {"attempt": n, "holding": holding, "time": time.strftime("%H:%M:%S")}
        attempts.append(rec)
        if not env.battery_ok():
            outcome = "battery"
            break
        say(f"attempt {n}: {'throw (holding the puck)' if holding else 'pick up and throw'}")
        t = env.throw(holding)
        rec["throw"] = {k: t.get(k) for k in ("ok", "fell", "path", "grip", "pack_pct", "burst")}
        if t.get("fell"):
            outcome = "fell"
            break
        if not t.get("ok"):
            outcome = "throw_failed"
            break
        holding = False
        try:
            basket, puck = env.look()
        except Fell:
            outcome = "fell"
            break
        code, words = classify_after(basket, puck)
        rec["after"] = {"code": code, "words": words, "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1)),
                        "basket": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1))}
        say(f"after the throw: {code}: {words}")
        if code != bo.MISSED:
            outcome = "made_or_lost" if code in (bo.NOT_SEEN, bo.MADE) else code
            break
        r = retrieve(env, say=say)
        rec["retrieval"] = r
        if r["outcome"] != "retrieved":
            outcome = r["outcome"]
            break
        lu = bl.lineup(env.quick_basket, env.mover, say=say)
        rec["lineup"] = {"outcome": lu["outcome"], "steps": lu["steps"]}
        if lu["outcome"] != "aligned":
            outcome = lu["outcome"]
            break
        holding = True
    return {"outcome": outcome, "attempts": attempts}


def write_log(result: dict, extra: dict | None = None, log_dir: str = LOG_DIR) -> str | None:
    try:
        d = os.path.expanduser(log_dir)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, time.strftime("%Y%m%d_%H%M%S") + "_basket_run.json")
        with open(path, "w") as f:
            json.dump({**result, **(extra or {})}, f, indent=1, default=str)
        return path
    except OSError:
        return None


class RealEnv:
    """G2 and his camera behind the `Env` interface: `throw`, `look`, `quick_basket`, `pick`, `battery_ok` and `mover`. Built once per run on one open serial link."""

    def __init__(self, link, robot, looker, book=None, burst: bool = True):
        from . import basket_movers as bm
        self.link, self.robot, self.looker = link, robot, looker
        self.mover = bm.BasketMover(robot, book=book)
        self._cam = None
        self.burst, self.run_stamp, self.attempt = burst, time.strftime("%Y%m%d_%H%M%S"), 0

    def _camera(self):
        from . import ball_chase as chase
        if self._cam is None:
            self.looker._ready.wait(10.0)
            self._cam = chase._SnapshotCamera(self.looker._cam)
        return self._cam

    def battery_ok(self) -> bool:
        return bool(self.robot.battery_ok())

    def throw(self, holding: bool) -> dict:
        from . import lob, scripted_skill
        argv = [lob.SCRIPT, "--amount", str(lob.AMOUNT), "--gyro-off", "--no-prompt"]
        if not holding:
            argv += ["--pick", "--pick-gap", str(lob.PICK_GAP_S), "--grip-look"]
        a = scripted_skill.parser().parse_args(argv)
        self.attempt += 1
        rec = None
        if self.burst and getattr(self.looker, "_ready", None) is not None and self.looker._ready.wait(10.0) and getattr(self.looker, "_cam", None) is not None:
            rec = BurstRecorder(self.looker._cam, os.path.join(os.path.expanduser(LOG_DIR), "burst", f"{self.run_stamp}_attempt{self.attempt}"))
        out = scripted_skill.play(a, scripted_skill.load_script(a.script), {}, link=self.link, robot=self.robot, looker=self.looker, rest_after=False, on_send=rec.start if rec else None)
        if rec is not None:
            out["burst"] = {"dir": rec.out_dir, "frames": len(rec.join())}
        self.robot.posture = "stand"
        self.robot._claw = (0.0, 0.0)
        res = out.get("res") or {}
        out["fell"] = bool(out.get("fell")) or res.get("verdict") == "fell"
        return out

    def look(self):
        """THE claw look (`claw_survey.run_claw_look`: the attention pose, the claw up, the pictures left, right and centre, the claw down, stand from the attention pose), every picture read by the basket and puck finders and merged into one body-frame reading each."""
        from . import ball_chase as chase
        from . import claw_survey
        from ..vision import basket_finder as bf
        from ..vision import puck_finder as pf
        cam, seen = self._camera(), {}
        left = chase.CLAW_PAN_DEG if chase.CLAW_PAN_SIGN == "left" else -chase.CLAW_PAN_DEG

        def snapshot(label):
            cam.refresh_exposure()
            jpeg = cam.look()
            if jpeg:
                basket = bf.find_basket(jpeg)
                seen[label] = (basket, pf.find_puck(jpeg, basket))
            return jpeg
        state = claw_survey.run_claw_look(self.link, snapshot, "centre", robot=self.robot)
        if state != "ok" and getattr(self.robot, "last_fall", None):
            raise Fell()
        return merge_looks(seen, {"look_left": -abs(left), "look_right": abs(left), "centre": 0.0})

    def quick_basket(self):
        """A quick picture with the claw down (no attention pose), the basket finder's reading or None."""
        from ..vision import basket_finder as bf
        cam = self._camera()
        cam.refresh_exposure()
        jpeg = cam.look()
        return bf.find_basket(jpeg) if jpeg else None

    def pick(self):
        from .catapult import pick_up
        ok = pick_up(self.link, seen=[])
        self.robot.posture = "stand"
        return "ok" if ok else "failed"


def main(argv: list | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="The full basket sequence on G2 (hands near, the voice service stopped, G2 at rest with the puck touching the claw tip and the basket 16 inches out).")
    ap.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    a = ap.parse_args(argv)
    from . import ball_chase as chase
    from . import chase_pace
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
    from .grip_look import GripLooker
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok or not imu_print.board_answers(link):
        print("not started: the pack gate failed or the board sent no motion data")
        return
    looker = GripLooker()
    looker.warm()
    robot = chase.SerialRobot(link)
    result = {"outcome": "not_run", "attempts": []}
    try:
        env = RealEnv(link, robot, looker, book=chase_pace.book_for_now(save=False))
        result = run_sequence(env, a.max_attempts)
    except KeyboardInterrupt:
        result["outcome"] = "interrupted"
    finally:
        looker.close()
        try:
            link._end_quiet()
        except Exception:  # noqa: BLE001
            pass
        chase.ensure_rest(link)
    path = write_log(result, {"pack_pct_start": pct})
    print("RESULT", result["outcome"], f"after {len(result['attempts'])} attempt(s); logged {path}")


if __name__ == "__main__":
    main()
