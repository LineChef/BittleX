"""The full basket sequence, as one process on one serial connection (the basket goal, docs/plan-detail/basket-goal-plan.md, steps 3 to 5; owner, 2026-11-23).

Per attempt: stand, pick the puck up, take the grip picture, throw (the lob: `behavior/lob.py` through `scripted_skill.play`); then ONE picture of the floor (the claw lowered from the throw's 125 degrees to AFTER_THROW_LIFT_DEG so the camera is level, read by the basket and puck finders) and straight into rest by the standard lie-down,
and the throw is classified (`goals/basket_outcome.classify_throw`). No attention pose: after `kcalib` the first byte the Pi sends makes the board start its own back-legs-first `up` and he falls (five runs, and a silence test on 2026-11-23: 14 s of silence and nothing, the next write and he stood up).
The puck seen on the floor outside the basket is a miss: he stands up from rest (the eased stand-up), searches for it (pivot scan, quick claw-down pictures), walks to it (the line-up's movers, the pace book's paces), walks the last inches and picks it up with `pickF`, checks by a picture that it is gone from the floor,
lines up on the basket again (`basket_lineup.lineup`: quick pictures with the claw down) and throws the next attempt without a pick-up (he already holds it). The puck not seen: counted as a make (owner, 2026-11-23) and the run stops for the owner's reset.
Stops: 5 attempts, a fall, a battery gate that fails, a camera that does not answer (checked before anything moves), no picture after the throw, a basket never found, a puck never found or reached, three failed pick-ups, and never closer than the line-up's buffer to the basket. Every stage is logged to `~/g2_runs/basket_run/` as it happens.

`next_retrieval_action` and `run_sequence` are pure (the robot, the camera and the throw are handed in as an `Env`), tested on a simulated floor; `RealEnv` wires them to G2 and is only used by `main`. UNPROVEN on G2: the first runs are watched by the owner (a separate process, `g2basket`).
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
BURST_S = 10.0                       # the picture burst (off by default; the arm stays up after the throw so it never saw the landing)
THROW_WATCH_S = 2.3                  # the body is watched this long after the throw is sent (the animation ends at about 2.2 s by the IMU trace; the default watch was about 3.1 s): the attention pose follows at once
AFTER_PICTURE_TIMEOUT_S = 2.5          # the camera's wait for one picture during the run
AFTER_THROW_LIFT_DEG = 76.0          # the claw angle that brings the camera level in the lob's end pose (125 deg minus the 49 deg the basket's row 210 against row 90 shows); to be checked on the first picture
KEEP_FRAMES = 4                      # the last frames of the burst kept in memory: the look after the throw reads them


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
    if basket is not None and (basket.claw_in < BASKET_GUARD_IN or getattr(basket, "touches_edge", False)):         # a basket cut off by the frame is right beside him
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


def camera_answers(looker, tries: int = 3, say=print) -> bool:
    """Is the camera answering? Called while G2 is still at rest, before anything moves: the first picture after a cold open can take about 10 s and a camera left stuck by an interrupted run gave no picture at all (2026-11-23), which held him standing with the puck and then in the attention pose."""
    if not looker._ready.wait(25.0) or getattr(looker, "_error", None) or getattr(looker, "_cam", None) is None:
        say("the camera did not open: " + str(getattr(looker, "_error", None) or "no answer"))
        return False
    for i in range(tries):
        try:
            if looker._cam.snapshot() is not None:
                return True
        except Exception:  # noqa: BLE001
            pass
        say(f"the camera gave no picture (try {i + 1} of {tries})")
    return False


class BurstRecorder:
    """The picture record of one throw (owner, 2026-11-23: see the puck leave the claw, its path, and the bounce or the miss). `start(t_send)` runs the camera's back-to-back burst in a thread; `join()` waits for it. The frames stay IN MEMORY: nothing is written to the
    disk (owner: the burst pictures are never saved); `sheet_png()` builds one labelled contact sheet for a review. The look after the throw reads the last frames. A diagnostic only: a failure here never stops the throw."""

    def __init__(self, cam, seconds: float = BURST_S, clock=time.monotonic):
        self.cam, self.seconds, self._clock = cam, seconds, clock
        self.thread = None
        self.t_send = None
        self.frames: list = []                # (seconds after the send the request went out, seconds after the send the picture arrived, jpeg)
        self.last_frames: list = []

    def start(self, t_send: float | None = None) -> None:
        import threading
        self.t_send = t_send if t_send is not None else self._clock()
        self.thread = threading.Thread(target=self._run, name="burst", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            got = self.cam.grab_burst(self.seconds)
            self.frames = [(t_req - self.t_send, t_got - self.t_send, jpeg) for t_req, t_got, jpeg in got]
            self.last_frames = [f[2] for f in self.frames[-KEEP_FRAMES:]]
        except Exception:  # noqa: BLE001
            pass

    def join(self, timeout: float = 15.0) -> list:
        if self.thread is not None:
            self.thread.join(timeout)
        return self.frames

    def sheet_png(self, cols: int = 8, side: int = 210) -> bytes | None:
        """One contact sheet of every frame, each labelled with the second it arrived after the send, as PNG bytes (None when there are no frames or no imaging library)."""
        if not self.frames:
            return None
        try:
            import io

            from PIL import Image, ImageDraw
            rows = (len(self.frames) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * side, rows * (side + 16)), (20, 20, 20))
            draw = ImageDraw.Draw(sheet)
            for i, (_t_req, t_got, jpeg) in enumerate(self.frames):
                x, y = (i % cols) * side, (i // cols) * (side + 16)
                sheet.paste(Image.open(io.BytesIO(jpeg)).convert("RGB").resize((side, side)), (x, y + 16))
                draw.text((x + 3, y + 2), f"#{i} got {t_got:+.2f}s", fill=(255, 255, 255))
            out = io.BytesIO()
            sheet.save(out, "PNG")
            return out.getvalue()
        except Exception:  # noqa: BLE001
            return None


def lob_end_lift() -> float:
    """The lift angle the lob's last frame leaves the arm at (from the script itself, so a changed script is followed)."""
    from . import lob, scripted_skill
    plan = scripted_skill.build_plan(scripted_skill.load_script(lob.SCRIPT), [0] * 8 + [20, 20, 30, 30, 30, 30, 30, 30], amount=lob.AMOUNT)
    return float(plan[-1]["frame"][1])


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


def retrieve(env, say=print, on_step=None) -> dict:
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
        if on_step is not None:
            on_step(st.log)
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


def run_sequence(env, max_attempts: int = MAX_ATTEMPTS, say=print, save=None) -> dict:
    """The attempts. Returns {"outcome": ..., "attempts": [...]}; the outcome says why it stopped: "made" (stop for the owner's reset), "max_attempts", "fell", "battery", "throw_failed",
    "basket_not_found", "could_not_align", "puck_not_found", "could_not_reach_puck", "too_near_the_basket", "pick_failed"."""
    attempts: list = []
    holding = False
    outcome = "max_attempts"

    def persist(state="running"):
        if save is not None:
            save({"outcome": state, "attempts": attempts})

    for n in range(1, max_attempts + 1):
        rec: dict = {"attempt": n, "holding": holding, "time": time.strftime("%H:%M:%S")}
        attempts.append(rec)
        persist()
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
        persist()
        try:
            basket, puck = env.after_throw()
        except Fell:
            outcome = "fell"
            break
        if not getattr(env, "picture_ok", True):
            rec["after"] = {"code": "no_picture", "words": "The camera gave no picture after the throw, so I cannot say where it went."}
            say("after the throw: no picture from the camera: stopping (not counted as a make)")
            outcome = "no_picture"
            persist()
            break
        code, words = classify_after(basket, puck)
        rec["after"] = {"code": code, "words": words, "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1)),
                        "basket": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1))}
        say(f"after the throw: {code}: {words}")
        persist()
        if code != bo.MISSED:
            outcome = "made" if code in (bo.NOT_SEEN, bo.MADE) else code            # owner, 2026-11-23: not seen by the end of the attention pose means it went in
            if code == bo.NOT_SEEN:
                say("the puck was not seen by the end of the attention pose: counted as a make")
            break
        def on_step(log, rec=rec):
            rec["retrieval"] = {"outcome": "running", "steps": list(log)}
            persist()
        r = retrieve(env, say=say, on_step=on_step)
        rec["retrieval"] = r
        persist()
        if r["outcome"] != "retrieved":
            outcome = r["outcome"]
            break
        lu = bl.lineup(env.quick_basket, env.mover, say=say)
        rec["lineup"] = {"outcome": lu["outcome"], "steps": lu["steps"]}
        persist()
        if lu["outcome"] != "aligned":
            outcome = lu["outcome"]
            break
        holding = True
    return {"outcome": outcome, "attempts": attempts}


def write_log(result: dict, extra: dict | None = None, log_dir: str = LOG_DIR, path: str | None = None) -> str | None:
    try:
        d = os.path.expanduser(log_dir)
        os.makedirs(d, exist_ok=True)
        path = path or os.path.join(d, time.strftime("%Y%m%d_%H%M%S") + "_basket_run.json")
        with open(path, "w") as f:
            json.dump({**result, **(extra or {})}, f, indent=1, default=str)
        return path
    except OSError:
        return None


class RealEnv:
    """G2 and his camera behind the `Env` interface: `throw`, `after_throw`, `look` (a quick picture), `quick_basket`, `pick`, `battery_ok` and `mover`. Built once per run on one open serial link."""

    def __init__(self, link, robot, looker, book=None, burst: bool = False, show_picture: bool = False):
        from . import basket_movers as bm
        self.link, self.robot, self.looker = link, robot, looker
        self.mover = bm.BasketMover(robot, book=book)
        self._cam = None
        self.burst, self.show_picture, self.run_stamp, self.attempt = burst, show_picture, time.strftime("%Y%m%d_%H%M%S"), 0
        self.quick_log: list = []
        self._burst_rec = None
        self.picture_ok = True
        try:
            looker._cam._timeout_s = AFTER_PICTURE_TIMEOUT_S              # a stalled camera ends a look in a few seconds, not eight a request
        except Exception:  # noqa: BLE001
            pass

    def _camera(self):
        from . import ball_chase as chase
        if self._cam is None:
            self.looker._ready.wait(10.0)
            self._cam = chase._SnapshotCamera(self.looker._cam)
        return self._cam

    def battery_ok(self) -> bool:
        return bool(self.robot.battery_ok())

    def throw(self, holding: bool) -> dict:
        """The lob (a pick-up first unless he already holds the puck)."""
        from . import ball_chase as chase
        from . import lob, scripted_skill
        argv = [lob.SCRIPT, "--amount", str(lob.AMOUNT), "--gyro-off", "--no-prompt", "--watch", str(THROW_WATCH_S)]
        if not holding:
            argv += ["--pick", "--pick-gap", str(lob.PICK_GAP_S), "--grip-look"]
        a = scripted_skill.parser().parse_args(argv)
        self.attempt += 1
        rec = None
        if self.burst and getattr(self.looker, "_ready", None) is not None and self.looker._ready.wait(10.0) and getattr(self.looker, "_cam", None) is not None:
            rec = BurstRecorder(self.looker._cam)
        out = scripted_skill.play(a, scripted_skill.load_script(a.script), {}, link=self.link, robot=self.robot, looker=self.looker, rest_after=False, on_send=rec.start if rec else None)
        self.robot.posture = "stand"
        self.robot._claw = (0.0, lob_end_lift())                            # the arm is where the throw's last frame left it (125 deg), not at 0: the move to the look angle starts from there
        res = out.get("res") or {}
        out["fell"] = bool(out.get("fell")) or res.get("verdict") == "fell"
        self._burst_rec = rec
        if rec is not None:
            out["burst"] = {"frames": len(rec.join())}
        return out

    def after_throw(self):
        """One picture of the floor after the throw, then rest (owner, 2026-11-23). NO attention pose: in five runs the first byte the Pi sent after `kcalib` made the board start its own back-legs-first `up` and he fell. The lob's end pose leaves the camera looking about 49 degrees
        too high (the basket at row 210 instead of 90), so the claw is lowered from the throw's 125 degrees to AFTER_THROW_LIFT_DEG, the picture is taken and the standard lie-down (the one every lob ends with) follows at once. The picture is never saved on the Pi; with show_picture it is printed (base64, one line)."""
        from . import ball_chase as chase
        from ..vision import basket_finder as bf
        from ..vision import puck_finder as pf
        r = self.robot
        if r.claw_pose(0.0, AFTER_THROW_LIFT_DEG) == "fell":
            raise Fell()
        time.sleep(chase.CLAW_SETTLE_S)
        cam = self._camera()
        cam.refresh_exposure()
        jpeg = cam.look()
        self.picture_ok = jpeg is not None
        chase.ensure_rest(self.link)
        r.posture, r._claw = "rest", (0.0, 0.0)
        basket = puck = None
        if jpeg:
            basket = bf.find_basket(jpeg)
            puck = pf.find_puck(jpeg, basket)
            if self.show_picture:
                import base64
                print(f"AFTER_PICTURE {self.attempt} {base64.b64encode(jpeg).decode()}", flush=True)
        return basket, puck

    def _ready_to_move(self) -> None:
        """From the attention pose with the claw up: the claw down, laid in rest, then the eased stand-up from rest (owner, 2026-11-23: a stand-up straight from the attention pose is a fall every time). Standing already: nothing."""
        posture = getattr(self.robot, "posture", "stand")
        if posture == "attention":
            if self.robot.rest_then_stand() == "fell":
                raise Fell()
        elif posture == "rest":
            if self.robot.stand_up_from_rest() == "fell":                       # the eased stand-up from rest (stand_up() sends nothing in the standing flow)
                raise Fell()

    def _quick(self, by: str):
        """One quick picture with the claw down: (basket reading, puck reading), the picture saved with the readings for the next fit."""
        from ..vision import basket_finder as bf
        from ..vision import puck_finder as pf
        self._ready_to_move()
        cam = self._camera()
        cam.refresh_exposure()
        jpeg = cam.look()
        if not jpeg:
            return None, None
        basket = bf.find_basket(jpeg)
        puck = pf.find_puck(jpeg, basket, by=by)
        n = len(self.quick_log) + 1
        d = os.path.join(os.path.expanduser(LOG_DIR), "quick", self.run_stamp)
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"q{n:02d}.jpg"), "wb") as f:
                f.write(jpeg)
        except OSError:
            pass
        self.quick_log.append({"n": n, "time": time.strftime("%H:%M:%S"),
                               "basket": None if basket is None else (round(basket.claw_in, 1), round(basket.bearing_deg, 1), basket.width_px),
                               "puck": None if puck is None else (round(puck.claw_in, 1), round(puck.bearing_deg, 1), puck.width_px, round(puck.y))})
        return basket, puck

    def look(self):
        """The retrieval's look: a quick claw-down picture, as the ball goal takes while it walks up (the puck's distance from its width)."""
        return self._quick("width")

    def quick_basket(self):
        """The line-up's look: a quick claw-down picture, the basket's reading or None."""
        return self._quick("width")[0]

    def pick(self):
        from .catapult import pick_up
        ok = pick_up(self.link, seen=[])
        self.robot.posture = "stand"
        return "ok" if ok else "failed"


def main(argv: list | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="The full basket sequence on G2 (hands near, the voice service stopped, G2 at rest with the puck touching the claw tip and the basket 16 inches out).")
    ap.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    ap.add_argument("--show-picture", action="store_true", help="after each throw print the picture of the floor (JPEG, base64, one line) for the person running it; never saved on the Pi")
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
    if not camera_answers(looker):
        print("not started: the camera is not answering (check its USB plug); nothing was moved")
        looker.close()
        return
    robot = chase.SerialRobot(link)
    result = {"outcome": "not_run", "attempts": []}
    path = os.path.join(os.path.expanduser(LOG_DIR), time.strftime("%Y%m%d_%H%M%S") + "_basket_run.json")
    env = None
    try:
        env = RealEnv(link, robot, looker, book=chase_pace.book_for_now(save=False), show_picture=a.show_picture)
        result = run_sequence(env, a.max_attempts, save=lambda r: (result.update(r), write_log(r, {"pack_pct_start": pct, "quick": env.quick_log}, path=path)))
    except KeyboardInterrupt:
        result["outcome"] = "interrupted"
    finally:
        looker.close()
        try:
            link._end_quiet()
        except Exception:  # noqa: BLE001
            pass
        chase.ensure_rest(link)
    path = write_log(result, {"pack_pct_start": pct, "quick": env.quick_log if env else []}, path=path)
    print("RESULT", result["outcome"], f"after {len(result['attempts'])} attempt(s); logged {path}")


if __name__ == "__main__":
    main()
