"""Chase the treat ball and punt it for the cat (user, 2026-10-25). Stop, look, step: a picture, one short move, a picture again, until someone says stop.

G2 cannot grab the 3 in ball (the claw opens to about 2.75 in), but `kpickF` throws it straight ahead, which is what the cat game needs. The loop:

  SEARCH   no ball in the picture: turn toward the side it was last seen on, else in 35 deg steps all the way round, a short walk after a full circle
  TURN     the ball is more than 12 deg off straight: turn toward it
  WALK     it is straight ahead but farther than 7 in (measured from the camera): walk up to it, never more than 3 s at a time: look again
  PUNT     it is within 6 in ahead and within 12 deg of straight: `kpickF` (never backs up for being too close: right in front of the ball, punt); then look where it went, and step closer if it is still more than 4 in away
  BACK UP  it is still where it was after three punts: back up, then line it up again

Pure logic in `ChasePlanner` (a reading in, an `Action` out) so it runs against a recorded picture series; `run_chase` is the loop around it with a robot, a camera, a stop flag and a picture saver
(every picture with the ball found goes to the training set, at most one per 2 s: user, 2026-10-25). Walks, turns and the punt are Petoi's own firmware skills (`kwkF`, `kwkL` / `kwkR`, `kbkF`,
`kpickF`) because they are the steadiest with the claw fitted; the link turns the gyro assist back off after each (fall recovery is off for the arm).

    python -m pi_pipeline.behavior.ball_chase            # on the Pi, voice service stopped, G2 standing; Ctrl-C or `touch ~/.local/share/g2/ball_chase_stop` ends it
    python -m pi_pipeline.behavior.ball_chase --dry-run  # looks and says what it would do; sends no move
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from ..vision.ball_finder import BallReading, find_ball

log = logging.getLogger("g2.ball_chase")

TURN_DEG_S = 6.0               # Petoi's arm turn (kwkL / kwkR), measured 2026-10-25: 30 deg in 4.8 s
WALK_IN_S = 5.8                # Petoi's arm walk (kwkF): about 5 to 6 in a second once it is going (2026-10-25: 7 in in a 1.9 s step)
WALK_START_S = 0.7             # a firmware gait covers nothing in its first 0.7 s or so
ALIGN_DEG = 12.0               # farther off straight than this: turn before walking
PUNT_ALIGN_DEG = 12.0          # ... and before a punt
PUNT_MIN_IN, PUNT_MAX_IN = 0.0, 4.0      # camera to ball: the lunge reaches about this far (2.6 in threw the ball 18 in; 4.5 to 5 in was just out of reach, 2026-10-25)
NUDGE_MAX_IN = 7.0             # between PUNT_MAX_IN and this: small steps closer, then punt anyway after NUDGES_BEFORE_PUNT of them
NUDGE_S = 0.9
NUDGES_BEFORE_PUNT = 3      # camera to ball, measured 2026-10-25: the ball at 2.6 in is a good punt (the claw hits it first and it goes straight ahead); at 4.5 in it is too far to be hit
WALK_MAX_S = 3.0               # one walk step: then look again
SEARCH_STEP_DEG = 20.0          # (was 35: a wrong turn away from a ball that was only missed once cost 6 s and the ball)
LOST_LOOKS = 3                 # real misses in a row before searching starts; a missing picture is not a miss
SEARCH_STEPS_PER_CIRCLE = 10
MAX_TURN_DEG = 35.0
MIN_MOVE_S = 1.2               # a gait started and stopped for less than this does not move him
CLOSE_IN_IN = 4.0              # after a punt that left the ball farther than this, step closer before the next one (2026-10-25: a punt from 4.5 to 7 in was too far, from 2.6 in it threw the ball 18 in)
STUCK_PUNTS = 3                # punts with the ball still in range before backing up
BACK_UP_S = 2.0
SAVE_EVERY_S = 2.0
PUNT_MIN_SWING_DEG = 6.0       # a real kpickF swings the pitch 15 to 20 deg
STOP_FILE = "~/.local/share/g2/ball_chase_stop"


@dataclass(frozen=True)
class Action:
    kind: str                  # "turn" | "walk" | "punt" | "back" | "look" | "search_turn" | "search_walk"
    seconds: float = 0.0
    degrees: float = 0.0       # + = right, - = left
    why: str = ""


@dataclass
class ChasePlanner:
    last_side: int = 0         # +1 the ball was last seen to the right, -1 to the left, 0 never
    lost: int = 0              # looks in a row without the ball
    search_steps: int = 0
    punts_in_range: int = 0
    after_punt: bool = False   # the last action was a punt
    nudges: int = 0            # small steps closer taken since the ball was last far or in reach
    last_dist: float | None = None   # how far the ball was when it was last seen (None once acted on)
    log: list = field(default_factory=list)

    def decide(self, ball: BallReading | None) -> Action:
        if ball is None:
            self.lost += 1
            self.punts_in_range = 0
            self.nudges = 0
            if self.last_dist is not None and self.last_dist <= NUDGE_MAX_IN:      # it was right there and now it is gone: at the claw, too close for the camera to see (user, 2026-10-25: right in front of the ball and no punt, then a turn away)
                self.last_dist = None
                self.lost = 0
                self.after_punt = True
                return Action("punt", 0.0, why="the ball vanished at close range: it is at the claw: punt")
            if self.lost < LOST_LOOKS:
                return Action("look", 1.0, why=f"no ball ({self.lost} of {LOST_LOOKS}): look again before searching")
            self.search_steps += 1
            if self.search_steps > SEARCH_STEPS_PER_CIRCLE:
                self.search_steps = 0
                return Action("search_walk", 2.0, why="a full circle without the ball: walk on and search again")
            side = self.last_side or 1
            return Action("search_turn", abs(SEARCH_STEP_DEG) / TURN_DEG_S, SEARCH_STEP_DEG * side, f"searching {'right' if side > 0 else 'left'}")
        self.lost = 0
        self.search_steps = 0
        self.last_dist = ball.distance_in
        self.last_side = 1 if ball.bearing_deg >= 0 else -1
        near = ball.distance_in <= NUDGE_MAX_IN
        in_reach = ball.distance_in <= PUNT_MAX_IN
        if near and not in_reach and abs(ball.bearing_deg) <= PUNT_ALIGN_DEG and self.nudges < NUDGES_BEFORE_PUNT:
            self.nudges += 1
            self.after_punt = False
            return Action("walk", NUDGE_S, why=f"ball {ball.distance_in:.0f} in ahead, just out of reach: a small step closer ({self.nudges} of {NUDGES_BEFORE_PUNT})")
        if abs(ball.bearing_deg) > (PUNT_ALIGN_DEG if near else ALIGN_DEG):
            deg = max(-MAX_TURN_DEG, min(MAX_TURN_DEG, ball.bearing_deg))
            return Action("turn", max(MIN_MOVE_S, abs(deg) / TURN_DEG_S), deg, f"ball {ball.bearing_deg:+.0f} deg off straight: turn")
        if near and self.after_punt and ball.distance_in > CLOSE_IN_IN:
            self.after_punt = False
            return Action("walk", 0.9, why=f"ball still {ball.distance_in:.0f} in away after the punt: step closer")
        if near:
            self.after_punt = True
            self.punts_in_range += 1
            if self.punts_in_range > STUCK_PUNTS:
                self.punts_in_range = 0
                return Action("back", BACK_UP_S, why="three punts and the ball has not left: back up")
            return Action("punt", 0.0, why=f"ball {ball.distance_in:.0f} in ahead, {ball.bearing_deg:+.0f} deg: punt")
        self.punts_in_range = 0
        self.after_punt = False
        self.nudges = 0
        secs = min(WALK_MAX_S, max(MIN_MOVE_S, WALK_START_S + (ball.distance_in - 4.0) / WALK_IN_S))      # aim for about 4 in: a gait needs WALK_START_S just to get moving, and the ball is touched at about 3 in
        return Action("walk", secs, why=f"ball {ball.distance_in:.0f} in ahead: walk {secs:.1f} s")


class Robot(Protocol):
    def walk(self, seconds: float) -> str: ...
    def turn(self, degrees: float, seconds: float) -> str: ...
    def back(self, seconds: float) -> str: ...
    def punt(self) -> str: ...
    def battery_ok(self) -> bool: ...


class Camera(Protocol):
    def look(self) -> bytes | None: ...


class SerialRobot:
    """The firmware skills over the serial link. Every move ends in a balanced stand (`kbalance`); the link sends `gb` after each skill. Each returns "ok" or "fell"."""

    def __init__(self, link, poll_imu=None, fall_deg: float = 45.0, sleep=time.sleep, clock=time.monotonic):
        self._lk, self._sleep, self._clock = link, sleep, clock
        self._fall_rad = math.radians(fall_deg)
        self._pitch, self._roll = [], []

    def _tx(self, c: str) -> None:
        self._lk.send(c, read_reply=False, settle=0.0)

    def _fell(self) -> bool:
        try:
            from ..gait.imu_parse import parse_imu_line
        except ImportError:
            from gait.imu_parse import parse_imu_line  # type: ignore
        for line in self._lk.poll_imu():
            r = parse_imu_line(line)
            if r is None:
                continue
            self._pitch.append(math.degrees(r[1]))
            self._roll.append(math.degrees(r[0]))
            if max(abs(r[0]), abs(r[1])) > self._fall_rad:
                return True
        return False

    def swing_deg(self) -> float:
        """How far the body tilted during the last skill (the larger of the pitch and roll ranges): 0 when it never moved."""
        rng = lambda v: (max(v) - min(v)) if len(v) > 1 else 0.0   # noqa: E731
        return max(rng(self._pitch), rng(self._roll))

    def _skill(self, token: str, seconds: float) -> str:
        self._pitch, self._roll = [], []
        self._tx("gP")
        self._tx(token)
        t0, state = self._clock(), "ok"
        while self._clock() - t0 < seconds:
            if self._fell():
                state = "fell"
                break
            self._sleep(0.05)
        if state == "ok":
            self._tx("kbalance")
            self._sleep(1.0)
        self._tx("gp")
        return state

    def walk(self, seconds: float) -> str:
        return self._skill("kwkF", seconds)

    def turn(self, degrees: float, seconds: float) -> str:
        return self._skill("kwkR" if degrees > 0 else "kwkL", seconds)

    def back(self, seconds: float) -> str:
        return self._skill("kbkF", seconds)

    def punt(self) -> str:
        state = self._skill("kpickF", 2.0)
        if state == "ok" and self.swing_deg() < PUNT_MIN_SWING_DEG:       # the lunge tilts the body 15 deg or more; if he barely moved, it did not play (2026-10-25: a run said "punted" and he only lay down): send it again once
            log.warning("the punt barely moved him (%.1f deg): sending it again", self.swing_deg())
            state = self._skill("kpickF", 2.0)
        return state

    def battery_ok(self) -> bool:
        from ..power import battery
        ok, pct, volts = battery.motion_gate(self._lk)
        if pct is None:
            log.warning("battery unreadable: stopping (fail safe)")
        else:
            log.info("battery %d%% (%.2f V)", pct, volts)
        return ok


class PictureSaver:
    """Saves each picture with the ball found plus its box (JSON beside it), at most one per SAVE_EVERY_S. Training data for the "ball" class (user, 2026-10-25)."""

    def __init__(self, folder: str, clock=time.monotonic):
        self._dir, self._clock, self._last = Path(os.path.expanduser(folder)), clock, -1e9
        self.saved = 0

    def maybe_save(self, jpeg: bytes, ball: BallReading | None, tag: str = "chase") -> None:
        if ball is None or self._clock() - self._last < SAVE_EVERY_S:
            return
        self._last = self._clock()
        self._dir.mkdir(parents=True, exist_ok=True)
        name = time.strftime(f"greenball_{tag}_%H%M%S")
        (self._dir / f"{name}.jpg").write_bytes(jpeg)
        mean = None
        try:                                                  # the sidecar format of the exploration pictures, so the review page (g2pics) lists them with the others
            import io

            import numpy as np
            from PIL import Image
            mean = round(float(np.asarray(Image.open(io.BytesIO(jpeg)).convert("L")).mean()), 1)
        except Exception:  # noqa: BLE001
            pass
        (self._dir / f"{name}.json").write_text(json.dumps({
            "file": f"{name}.jpg", "kind": "name:greenball", "pose": "named", "name": "greenball", "time": time.strftime("%Y-%m-%d %H:%M:%S"), "width": 240, "height": 240,
            "detections": [], "exposure": {"mean": mean}, "named_by": "ball_chase",
            "box_xywh": [round(ball.x - ball.width / 2), round(ball.y - ball.height / 2), ball.width, ball.height],
            "distance_in": round(ball.distance_in, 1), "bearing_deg": round(ball.bearing_deg, 1), "edge": ball.touches_edge}, indent=1))
        self.saved += 1


def run_chase(robot: Robot, camera: Camera, stop: Callable[[], bool], *, planner: ChasePlanner | None = None, saver: PictureSaver | None = None, dry_run: bool = False, announce: Callable[[str], None] | None = None,
              settle_s: float = 1.0, sleep=time.sleep, max_steps: int | None = None, max_punts: int | None = None, say: Callable[[str], None] = print) -> str:
    """Look, decide, move, until `stop()` or a fall or a low battery. Returns "stopped", "fell", "battery", "steps" or (with `max_punts`: one attempt = walk up and punt that many times) "punted".
    Never gives up on its own."""
    planner = planner or ChasePlanner()
    steps = 0
    punts = 0
    seen = False
    while not stop():
        if max_steps is not None and steps >= max_steps:
            return "steps"
        steps += 1
        if steps % 15 == 1 and not dry_run and not robot.battery_ok():
            say("battery low or unreadable: stopping")
            return "battery"
        sleep(settle_s)                                   # let the body stop swaying before the picture
        jpeg = camera.look()
        if not jpeg:                                      # the camera gave no picture: that says nothing about the ball (2026-10-25: counting it as a miss sent him turning away from a ball straight ahead)
            say(f"[{steps}] no picture from the camera: looking again")
            continue
        ball = find_ball(jpeg)
        if saver is not None:
            saver.maybe_save(jpeg, ball)
        if announce is not None:                          # real-time signal of what he sees (user, 2026-10-25): "searching" when a search starts, "target acquired" when the ball is found again
            if ball is not None and (planner.lost > 0 or planner.search_steps > 0 or not seen):
                announce("target acquired")
            elif ball is None and planner.lost + 1 == LOST_LOOKS:                       # the look that starts a search
                announce("searching")
        seen = seen or ball is not None
        act = planner.decide(ball)
        say(f"[{steps}] {'ball ' + format(ball.distance_in, '.0f') + ' in ' + format(ball.bearing_deg, '+.0f') + ' deg' if ball else 'no ball'} -> {act.kind}: {act.why}")
        if dry_run or act.kind == "look":
            if act.kind == "look":
                sleep(act.seconds)
            continue
        if act.kind in ("turn", "search_turn"):
            state = robot.turn(act.degrees, act.seconds)
        elif act.kind in ("walk", "search_walk"):
            state = robot.walk(act.seconds)
        elif act.kind == "back":
            state = robot.back(act.seconds)
        elif act.kind == "punt":
            if announce is not None:
                announce("punting")                       # he says it right before the lunge (user, 2026-10-25)
            state = robot.punt()
            punts += 1
            sleep(1.5)                                    # the ball is rolling: look after it stops
            if state != "fell" and max_punts is not None and punts >= max_punts:
                say(f"punted {punts}: done")
                return "punted"
        else:
            state = "ok"
        if state == "fell":
            say("G2 fell: stopping (fall recovery is off)")
            return "fell"
    return "stopped"


def stop_requested() -> bool:
    return os.path.exists(os.path.expanduser(STOP_FILE))


class _SnapshotCamera:
    def __init__(self, cam):
        self._cam = cam

    def look(self) -> bytes | None:
        snap = self._cam.snapshot()                      # exposure balancing stays on (user, 2026-10-25)
        return snap.jpeg if snap is not None else None


def _stand_if_lying(link) -> None:
    """If the legs read the rest pose, stand him up (the link runs the arm build's own stand-up for a kbalance from lying). Never raises."""
    import re
    try:
        s = link._ser
        s.reset_input_buffer()
        s.write(b"j\n")
        time.sleep(1.0)
        rows = [r for r in s.read(s.in_waiting or 1).decode("ascii", "ignore").splitlines() if r.count(",") >= 15]
        j = [int(x) for x in re.findall(r"-?\d+", rows[-1])] if rows else None
        if j is None or (j[8] < 40 and j[12] > 30):
            return
        print("lying down: standing up first")
        link.send("kbalance", read_reply=False, settle=0.0)
        time.sleep(3.0)
    except Exception as e:  # noqa: BLE001
        print("could not check the pose:", e)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Chase the green ball and punt it until stopped.")
    ap.add_argument("--dry-run", action="store_true", help="look and report what it would do; send no move")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--punts", type=int, default=None, help="stop after this many punts (one attempt: walk up to the ball and punt it); default: until stopped")
    ap.add_argument("--save-to", default="~/.local/share/g2/explore_pictures/named/greenball", help="folder for the pictures with the ball found (where g2pics reads them)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    from ..config import settings
    from ..link.serial_link import SerialLink
    from ..vision.snapshot import CameraSnapshotter
    p = Path(os.path.expanduser(STOP_FILE))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    link = SerialLink("/dev/serial0")
    link.connect()
    announce = None
    try:                                                 # the voice for "searching" / "target acquired"
        from ..voice.tts import make_tts
        _tts = make_tts("piper", piper_model_path=settings.piper_model_path, style=settings.voice_style)
        announce = lambda text: _tts.speak(text)         # noqa: E731
    except Exception as e:  # noqa: BLE001
        print("no voice (", e, "): the cues are printed only")
    _stand_if_lying(link)
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump)
    try:
        why = run_chase(SerialRobot(link), _SnapshotCamera(cam), stop_requested, saver=PictureSaver(args.save_to), dry_run=args.dry_run, max_steps=args.max_steps, max_punts=args.punts, announce=announce)
        print("ended:", why)
    except KeyboardInterrupt:
        print("ended: stopped")
    finally:
        cam.close()
        if not args.dry_run:                              # rest after each attempt (user, 2026-10-25); the next one stands him up first
            link.send("krest", read_reply=False, settle=0.0)
            time.sleep(2.5)


if __name__ == "__main__":
    main()
