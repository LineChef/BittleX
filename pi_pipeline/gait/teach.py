"""Teach G2 a leg movement by showing it: record poses, one step at a time, two ways.

  * HAND  -- `hand` relaxes the servos (rest `d`), you move a leg by hand, `grab` reads the eight leg angles back
             from the servo feedback (`f`, else `j`), `save` keeps the pose as a step.
  * JOG   -- G2 stands (eased), then you say "fl knee +5" (5 degrees more on that joint) or "fr shoulder 40" (to 40);
             he moves there, `save` keeps it.

The two work together: grab a pose by hand, then nudge it with jog commands, then save. Steps are written to a JSON file
(`reference_gait/build_taught_step.py` turns it into a walking reference). Angles are in URDF degrees, order
[FLs, FLk, FRs, FRk, BRs, BRk, BLs, BLk], the same as everything in `gait/`.

    python -m pi_pipeline.gait.teach [--out ~/g2_taught/hi_step.json] [--leg fl]

Safety: never move a leg by hand while the servos hold it (a powered servo can strip its gears). `hand` sends `d` first and
`grab` refuses unless the last motion command was `d`. Every move is eased (small `i` steps), single jogs are capped at 30
degrees, and the eased stand-up rule applies (`stand` goes through the serial link's ramp). The voice service must be stopped:
`bash tools/g2_safe_stop.sh voice`.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from . import standup

LEGS = ("fl", "fr", "br", "bl")
JOINT_NAMES = ("shoulder", "knee")           # a rear leg's shoulder servo is its hip
MAX_JOG_DEG = 30.0
LIMIT_DEG = 120.0


def joint_index(leg: str, joint: str) -> int:
    """URDF index of (leg, joint): leg*2 + 0 for shoulder / hip, +1 for knee."""
    leg = leg.lower()
    j = joint.lower()
    if leg not in LEGS:
        raise ValueError(f"leg must be one of {', '.join(LEGS)}")
    if j in ("s", "sh", "shoulder", "h", "hip"):
        return LEGS.index(leg) * 2
    if j in ("k", "kn", "knee"):
        return LEGS.index(leg) * 2 + 1
    raise ValueError("joint must be shoulder (hip) or knee")


def parse_jog(line: str, current: list[float]) -> list[float]:
    """`fl knee +5` -> that joint 5 degrees more; `fr shoulder 40` -> to 40; `bl hip -3`. Returns the new 8 angles.
    A leading + or - is a change, a bare number is the angle to go to."""
    parts = line.split()
    if len(parts) != 3:
        raise ValueError("say: <leg> <shoulder|knee> <+/-change or angle>   e.g. fl knee +5")
    k = joint_index(parts[0], parts[1])
    raw = parts[2]
    try:
        v = float(raw)
    except ValueError:
        raise ValueError(f"{raw!r} is not a number") from None
    new = list(current)
    if raw[0] in "+-":
        if abs(v) > MAX_JOG_DEG:
            raise ValueError(f"a single change is limited to {MAX_JOG_DEG:g} degrees")
        new[k] = current[k] + v
    else:
        if abs(v - current[k]) > MAX_JOG_DEG:
            raise ValueError(f"that is {abs(v - current[k]):.0f} degrees from now; limited to {MAX_JOG_DEG:g} per move (go in two)")
        new[k] = v
    if abs(new[k]) > LIMIT_DEG:
        raise ValueError(f"{new[k]:g} is outside +/-{LIMIT_DEG:g}")
    return new


def parse_angles(reply: str) -> list[float] | None:
    """Eight leg angles in URDF order from a servo-feedback / joint-read reply, or None.

    The reply format is not documented, so this reads every number in it: 16 numbers are all servos (legs are servo 8..15), 8 numbers are the legs
    in servo order [FLs, FRs, BRs, BLs, FLk, FRk, BRk, BLk]. Anything else is rejected. `check` against a commanded pose proves the mapping on G2."""
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", reply or "")]
    if len(nums) == 16:
        legs = nums[8:16]
    elif len(nums) == 8:
        legs = nums
    else:
        return None
    return [legs[i - 8] for i in standup._URDF_TO_SERVO]


def save_steps(path: Path, leg: str, steps: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "order": "urdf_deg", "leg": leg, "steps": steps}, indent=1))


def load_steps(path: Path) -> tuple[str, list[dict]]:
    d = json.loads(path.read_text())
    return d.get("leg", "fl"), list(d["steps"])


class Teacher:
    """The teaching session. `link` is a SerialLink (or anything with send()/drain()); `out` is the JSON file; `sleep` is injected for tests."""

    def __init__(self, link, out: Path, leg: str = "fl", say=print, sleep=time.sleep):
        self.link, self.out, self.leg, self.say, self.sleep = link, Path(out), leg, say, sleep
        self.current: list[float] | None = None          # where the legs are told to be (URDF deg)
        self.steps: list[dict] = []
        if self.out.exists():
            self.leg, self.steps = load_steps(self.out)
            self.say(f"loaded {len(self.steps)} steps from {self.out}")

    # --- moving ---
    def _move_to(self, target: list[float], seconds: float | None = None) -> None:
        start = self.current
        if start is None:
            self.link.send(standup.move_cmd(target), read_reply=False)
        else:
            delta = max(abs(a - b) for a, b in zip(start, target))
            secs = seconds if seconds is not None else max(0.25, delta / 40.0)
            for pose in standup.ramp_poses(start, target, secs):
                self.link.send(standup.move_cmd(pose), read_reply=False)
                self.sleep(1.0 / standup.STEPS_PER_S)
        self.current = list(target)

    def stand(self, pose: str = "balance") -> None:
        """Eased stand (the link ramps `kbalance` / `kup` out of rest). `sit` and `rest` are the other start poses."""
        token = {"balance": "kbalance", "up": "kup", "sit": "ksit", "rest": "d"}.get(pose)
        if token is None:
            raise ValueError("stand balance | up | sit | rest")
        self.link.send(token, read_reply=False)
        self.sleep(1.5)
        self.current = standup.start_pose(token)
        self.say(f"{pose}: " + self.fmt(self.current))

    def jog(self, line: str) -> None:
        if self.current is None:
            raise ValueError("stand first (or grab a pose by hand)")
        target = parse_jog(line, self.current)
        self._move_to(target)
        self.say(self.fmt(self.current))

    # --- hand teaching ---
    def hand(self) -> None:
        """Relax every servo so a leg can be moved by hand."""
        self.link.send("d", read_reply=False)
        self.sleep(1.5)
        self.current = None
        self._relaxed = True
        self.say("servos relaxed: move the leg by hand, then `grab`. Do not force a leg that is holding.")

    _relaxed = False

    def read(self) -> list[float] | None:
        for token in ("f", "j"):
            self.link.drain(0.2)
            got = parse_angles(self.link.send(token))
            if got is not None:
                return got
        return None

    def grab(self) -> None:
        if not self._relaxed:
            raise ValueError("run `hand` first so the servos are limp")
        got = self.read()
        if got is None:
            raise ValueError("no usable reading from the servos; try `raw` to see what came back")
        self.current = got
        self.say("read: " + self.fmt(got))

    def raw(self) -> None:
        for token in ("f", "j"):
            self.link.drain(0.2)
            self.say(f"{token}: {self.link.send(token)!r}")

    def hold(self) -> None:
        """Tell the servos to hold the grabbed pose (so jogs can start from it). The legs are already there, so nothing jumps."""
        if self.current is None:
            raise ValueError("grab a pose first")
        self.link.send(standup.move_cmd(self.current), read_reply=False)
        self._relaxed = False
        self.say("holding " + self.fmt(self.current))

    def check(self) -> None:
        """Prove the reading: command the balance pose, read it back, print the difference per joint. Run once per session before trusting `grab`."""
        self.stand("balance")
        got = self.read()
        if got is None:
            self.say("no usable reading (try `raw`)")
            return
        diffs = [round(g - c, 1) for g, c in zip(got, standup.BALANCE_URDF_DEG)]
        self.say("read    : " + self.fmt(got))
        self.say("commanded: " + self.fmt(standup.BALANCE_URDF_DEG))
        self.say("difference per joint: " + str(diffs) + ("  -> mapping looks right" if max(abs(d) for d in diffs) < 8 else "  -> MISMATCH: do not trust `grab` yet"))

    # --- steps ---
    def save(self, name: str = "") -> None:
        if self.current is None:
            raise ValueError("nothing to save yet")
        step = {"name": name or f"step{len(self.steps) + 1}", "deg": [round(a, 1) for a in self.current]}
        self.steps.append(step)
        save_steps(self.out, self.leg, self.steps)
        self.say(f"saved #{len(self.steps)} {step['name']}")

    def undo(self) -> None:
        if not self.steps:
            raise ValueError("no steps")
        gone = self.steps.pop()
        save_steps(self.out, self.leg, self.steps)
        self.say(f"removed {gone['name']}")

    def listing(self) -> None:
        for i, s in enumerate(self.steps, 1):
            self.say(f"{i:2d} {s['name']:10s} {self.fmt(s['deg'])}")
        if not self.steps:
            self.say("(no steps yet)")

    def goto(self, n: int) -> None:
        if not 1 <= n <= len(self.steps):
            raise ValueError(f"step 1..{len(self.steps)}")
        self._move_to(self.steps[n - 1]["deg"])
        self.say(f"at #{n}")

    def play(self, seconds_each: float = 1.0) -> None:
        if self.current is None:
            raise ValueError("stand first")
        for i, s in enumerate(self.steps, 1):
            self._move_to(s["deg"], seconds=seconds_each)
            self.say(f"#{i} {s['name']}")
            self.sleep(0.3)

    def rest(self) -> None:
        self.link.send("d", read_reply=False)
        self.current = None
        self._relaxed = True

    @staticmethod
    def fmt(deg) -> str:
        names = ("FLs", "FLk", "FRs", "FRk", "BRs", "BRk", "BLs", "BLk")
        return " ".join(f"{n}={d:.0f}" for n, d in zip(names, deg))


HELP = """commands:
  stand [balance|up|sit|rest]   eased stand (start of a jog session)
  <leg> <shoulder|knee> <+n|-n|angle>   jog, e.g.  fl knee +5   fr shoulder 40   (legs: fl fr br bl)
  hand                          relax the servos so you can move a leg by hand
  grab                          read the eight angles from the servos (after `hand`)
  hold                          make the servos hold the grabbed pose (then jog from it)
  check                         stand, read back, compare: proves `grab` is right (do once)
  raw                           show the raw feedback replies
  save [name]   undo   list   goto N   play [seconds per step]
  rest   help   quit"""


def run_repl(t: Teacher, read=input) -> None:
    t.say(HELP)
    while True:
        try:
            line = read("teach> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        cmd, _, rest = line.partition(" ")
        try:
            if cmd in ("quit", "q", "exit"):
                break
            elif cmd == "help":
                t.say(HELP)
            elif cmd == "stand":
                t.stand(rest.strip() or "balance")
            elif cmd == "hand":
                t.hand()
            elif cmd == "grab":
                t.grab()
            elif cmd == "hold":
                t.hold()
            elif cmd == "check":
                t.check()
            elif cmd == "raw":
                t.raw()
            elif cmd == "save":
                t.save(rest.strip())
            elif cmd == "undo":
                t.undo()
            elif cmd == "list":
                t.listing()
            elif cmd == "goto":
                t.goto(int(rest))
            elif cmd == "play":
                t.play(float(rest) if rest.strip() else 1.0)
            elif cmd == "rest":
                t.rest()
            else:
                t.jog(line)
        except ValueError as e:
            t.say(f"! {e}")
    t.rest()


def main() -> None:
    from ..config import settings
    from ..link.serial_link import SerialLink

    ap = argparse.ArgumentParser(prog="pi_pipeline.gait.teach", description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(Path.home() / "g2_taught" / "step.json"))
    ap.add_argument("--leg", default="fl", choices=LEGS, help="the leg you are teaching (the builder copies it to the other three)")
    args = ap.parse_args()
    link = SerialLink(settings.serial_port, settings.serial_baud)
    if not link.connect():
        raise SystemExit(f"could not open {settings.serial_port} (is the voice service stopped?)")
    try:
        run_repl(Teacher(link, Path(args.out), args.leg))
    finally:
        link.close()


if __name__ == "__main__":
    main()
