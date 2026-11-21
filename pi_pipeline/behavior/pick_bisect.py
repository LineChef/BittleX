"""The pick-up bisect: what does it take to cut `kpickF` short? (hardware test, docs/hardware/arm-skills.md; plan item 3 in docs/STATUS.md)

Use it only if `g2armskill pickF` still does not play in full after the link's silence fix: it separates the skill from everything the Pi writes around it. One run = one variant, G2 standing after the eased stand-up, the
person's go before each, hands near, the voice service stopped (`g2pickbisect`). It writes `kpickF` straight to the port, the way `printf 'kpickF\\n' > /dev/serial0` does (which played in full by hand), then writes at most
one extra command a little later, and nothing else for `--silent` seconds while the IMU is only read. The person types what the claw did, and the body trace says whether he moved.

Variants (the extra command written `--after-ms` after the token, 100 by default):
  plain  nothing extra: the reference, expected to play in full (what the hand-typed command did).
  gb     `gb` (the byte the old link wrote right behind every skill): expected to cut it short.
  gP     `gP` (the IMU print on, which the older test tools sent): expected to cut it short.
  j      `j` (a joint read, which the old `--joints` option sent): expected to cut it short.
  link   the token goes through the link's own `send` (the fixed path `g2armskill` uses): expected to play in full.
The first variant to run is `plain`. If it plays in full the others say which write cuts a skill; if it does not, the stand-up path or the board is the next thing to look at.

    python -m pi_pipeline.behavior.pick_bisect --variant plain
"""
from __future__ import annotations

import json
import os
import time

from . import arm_skill_test as ast

VARIANTS = ("plain", "gb", "gP", "j", "link")
SILENT_S = 10.0
AFTER_MS = 100
LOG_DIR = "~/g2_runs/pick_bisect"
RESULTS = {"f": "full pick", "p": "partly", "n": "claw did not move", "u": "stood up instead"}


def make_sender(link, variant: str, after_ms: int = AFTER_MS, sleep=time.sleep):
    """The function that puts the skill on the wire for `variant`; `link.write_raw` for the raw ones (nothing logged by the link), `link.send` for `link`. Raises ValueError for an unknown variant."""
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}")
    if variant == "link":
        return lambda: link.send("kpickF", read_reply=False, settle=0.0)
    extra = None if variant == "plain" else variant

    def send():
        link.write_raw(b"kpickF\n")
        if extra is not None:
            sleep(after_ms / 1000.0)
            link.write_raw((extra + "\n").encode("ascii"))
    return send


def run_variant(robot, link, variant: str, *, silent_s: float = SILENT_S, after_ms: int = AFTER_MS, say=print, sleep=time.sleep, clock=time.monotonic, wall=time.time) -> dict:
    """Play one variant from a stand and watch the body for `silent_s` seconds (the IMU is read, nothing is written). Returns the arm-skill test's result dict plus the variant."""
    res = ast.run_skill(robot, "pickF", watch_s=silent_s, say=say, sleep=sleep, clock=clock, wall=wall, send=make_sender(link, variant, after_ms, sleep), expect_motion=True)
    res["variant"], res["after_ms"] = variant, after_ms
    return res


def ask_result(ask=input) -> dict:
    """What the person saw, typed in after the run: one letter, then a note."""
    try:
        r = ask("what did the claw do? f full pick (opened and closed on the object), p partly, n did not move, u he stood up instead: ").strip().lower()[:1]
        return {"result": RESULTS.get(r), "note": ask("note (Enter = none): ").strip() or None}
    except EOFError:
        return {"result": None, "note": None}


def write_log(res: dict, extra: dict | None = None) -> str | None:
    try:
        d = os.path.expanduser(LOG_DIR)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, time.strftime("%Y%m%d_%H%M%S") + "_" + res["variant"] + ".json")
        with open(path, "w") as f:
            json.dump({**res, **(extra or {}), "time": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=1)
        return path
    except OSError:
        return None


def main() -> None:
    import argparse

    from . import ball_chase as chase
    ap = argparse.ArgumentParser(description="One pick-up bisect variant on G2: the person's go first; the voice service stopped.")
    ap.add_argument("--variant", required=True, choices=VARIANTS)
    ap.add_argument("--silent", type=float, default=SILENT_S, help="seconds to write nothing after the token")
    ap.add_argument("--after-ms", type=int, default=AFTER_MS, help="milliseconds after the token the one extra command is written")
    ap.add_argument("--object", default=None)
    ap.add_argument("--floor", default=None)
    ap.add_argument("--no-prompt", action="store_true")
    args = ap.parse_args()
    from ..link import imu_print
    from ..link.serial_link import SerialLink
    from ..power import battery
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    if not imu_print.board_answers(link):
        print("refused: no IMU frames from the BiBoard: is it powered on? Nothing was sent.")
        return
    robot = chase.SerialRobot(link)
    path = None
    try:
        chase._stand_if_lying(link, "kbalance")
        res = run_variant(robot, link, args.variant, silent_s=args.silent, after_ms=args.after_ms)
        path = write_log(res, {"pack_pct": pct, "pack_v": volts, "object": args.object, "floor": args.floor})
        print(f"RESULT pickF variant {args.variant}: body {res['verdict']} (roll {res['max_roll_dev']} pitch {res['max_pitch_dev']} deg){'; logged ' + path if path else ''}")
    except KeyboardInterrupt:
        print("ended")
    finally:
        chase.ensure_rest(link)
    if path and not args.no_prompt:
        ast.update_log(path, {"observed": ask_result()})


if __name__ == "__main__":
    main()
