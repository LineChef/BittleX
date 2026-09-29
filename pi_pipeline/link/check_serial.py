"""Serial-link diagnostics for the BiBoard. Needs pyserial + a connected robot.

    python -m pi_pipeline.link.check_serial ports              # list serial ports
    python -m pi_pipeline.link.check_serial ping               # open the configured port, poke it
    python -m pi_pipeline.link.check_serial send kbalance       # send one command, print the reply
    python -m pi_pipeline.link.check_serial burst kwkR --seconds 1.5  # run a gait briefly, then auto-rest -- one connection, no reboot mid-move
    python -m pi_pipeline.link.check_serial skills              # cycle the conversational skill set
    python -m pi_pipeline.link.check_serial rest                # send 'd' (safe state)
    python -m pi_pipeline.link.check_serial feedback            # before/after 'f' reads around a hand-moved leg, one connection -- is servo feedback real?
    python -m pi_pipeline.link.check_serial firstmove           # guided, confirmed first movement
    python -m pi_pipeline.link.check_serial allmoves            # cycle EVERY known move + log voltage/latency
    python -m pi_pipeline.link.check_serial allmoves --skip-gaits --skip-recovery  # stationary moves only
"""
from __future__ import annotations

import argparse
import logging
import time

from ..config import settings
from ..diag import diag
from ..voice import skills as skillcat
from . import opencat
from .serial_link import SerialLink


def _link() -> SerialLink:
    return SerialLink(settings.serial_port, settings.serial_baud)


# name -> OpenCat servo index (deploy_map.py's confirmed Petoi joint map).
# Head first (index 0, lowest stakes), then the 8 leg servos.
_JOINTS = [
    ("head-pan", 0),
    ("FL-shoulder", 8), ("FR-shoulder", 9), ("BR-shoulder", 10), ("BL-shoulder", 11),
    ("FL-knee", 12), ("FR-knee", 13), ("BR-knee", 14), ("BL-knee", 15),
]


def _firstmove(link: SerialLink, *, deg: float, walk_s: float) -> None:
    """One joint at a time through a small range of motion, each step
    confirmed, before ever trying `kbalance` or a walk gait. Always leaves the
    robot at `d` (rest) on exit, including on Ctrl-C."""
    print(f"Guided first movement -- {deg:g} degree nudge per joint, confirmed each step.")
    print("Enter = do it, s = skip this joint, q = stop here (and rest).\n")
    try:
        for name, idx in _JOINTS:
            choice = input(f"  nudge {name} (servo {idx}) by +{deg:g} deg? [Enter/s/q] "
                          ).strip().lower()
            if choice == "q":
                break
            if choice == "s":
                continue
            link.send(opencat.move_joints([(idx, int(deg))]), read_reply=False)
            after = input(f"    watch it, then Enter to return {name} to neutral "
                         f"(or q to stop here)... ").strip().lower()
            if after == "q":
                break
            link.send(opencat.move_joints([(idx, 0)]), read_reply=False)
        else:
            choice = input("\nAll joints checked. Send kbalance (robot stands)? "
                          "[Enter/q] ").strip().lower()
            if choice != "q":
                link.send(opencat.BALANCE, read_reply=False)
                choice = input(f"\nStanding OK? Run kwkF for {walk_s:g}s then auto-rest? "
                              "[Enter/q] ").strip().lower()
                if choice != "q":
                    link.send(opencat.skill("wkF"), read_reply=False)
                    time.sleep(walk_s)
    finally:
        link.send(opencat.REST, read_reply=False)
        print("sent 'd' (rest) -- first-move check done.")


def _burst(link: SerialLink, token: str, seconds: float) -> None:
    """Run one command for a fixed duration then auto-rest, in a single
    connection. Two separate `check_serial send` calls (move, then a second
    process sending `d`) each open their own connection -- and opening the
    port reboots the BiBoard (SerialLink's reset_wait), which could land
    mid-stride. This does move+hold+rest without a second reboot in between."""
    print(f"Sending {token!r} for {seconds:g}s, then rest.")
    link.send(token, read_reply=False)
    time.sleep(seconds)
    link.send(opencat.REST, read_reply=False)
    print("sent 'd' (rest)")


def _feedback_check(link: SerialLink) -> None:
    """Query 'f' (T_SERVO_FEEDBACK) once, then again after the user manually
    repositions a leg -- in ONE connection, so a board reboot between reads
    (every separate check_serial invocation reboots the board -- see _burst)
    can't confound whether a difference reflects a real sensor read vs just
    post-reboot state. If the second reading tracks the hand-moved position,
    feedback is real; if it's unchanged, that's consistent with a fallback to
    the last commanded angle rather than a true sensor read -- see the
    connectedFeedbackServo note in docs/hardware/petoi-firmware-reference.md."""
    link.drain(0.3)
    before = (link.send(opencat.SERVO_FEEDBACK) or "").strip()
    print(f"reading 1 (before): {before!r}")
    input("\nNow move one leg by hand to a clearly different position, "
         "then press Enter... ")
    link.drain(0.3)
    after = (link.send(opencat.SERVO_FEEDBACK) or "").strip()
    print(f"reading 2 (after) : {after!r}")
    if before and after and before != after:
        print("Different -- consistent with real position feedback.")
    elif before and after:
        print("Same/unchanged -- consistent with NOT real feedback "
             "(likely just reporting the last commanded angle).")
    else:
        print("Inconclusive -- one or both reads came back empty.")


def _all_moves() -> list:
    """(name, token, kind) for every distinct movement G2 knows how to
    perform, deduped by the resulting serial token. Two catalogues that don't
    otherwise overlap: `voice/skills.py` (what Claude can invoke by
    conversation) and `behavior/gestures.py` (what the autonomous behaviour
    layer fires on its own -- greetings, idle fidgets, the excited hop) --
    plus sleep, the carpet gait, and the recovery/get-up keyframes, none of
    which either catalogue covers. `kind` is one of gait/skill/gesture/sleep/
    carpet/recovery -- `gait` is any continuous locomotion skill (walk/trot/
    crawl) per `Skill.continuous`, so it can be filtered out as a group
    (`--skip-gaits`) same as recovery keyframes; recovery keyframes are
    always last."""
    from ..behavior.gestures import GESTURE_TOKEN

    seen: dict = {}
    for name, sk_ in skillcat.SKILLS.items():
        tok = skillcat.serial_command(name)
        seen.setdefault(tok, (name, tok, "gait" if sk_.continuous else "skill"))
    for g, tok in GESTURE_TOKEN.items():
        seen.setdefault(tok, (g.value, tok, "gesture"))
    seen.setdefault(opencat.SLEEP, ("sleep", opencat.SLEEP, "sleep"))
    seen.setdefault(opencat.CARPET_WALK, ("carpet-walk", opencat.CARPET_WALK, "carpet"))

    ordered = list(seen.values())
    ordered += [
        ("self-right", opencat.RECOVER, "recovery"),
        ("roll-from-supine", opencat.ROLL_OVER, "recovery"),
        ("drop-recover", opencat.DROP_RECOVER, "recovery"),
    ]
    return ordered


def _read_voltage(link: SerialLink, *, attempts: int = 4, drain_s: float = 0.2) -> str:
    """Query battery voltage, draining before each attempt and retrying past
    any stray non-voltage line still in flight. Confirmed on real hardware
    2026-09-28 that one drain() pass isn't always enough: some skills (wave,
    push_ups, check_around, come_here, high_five) print a firmware debug line
    (`imuException: 0`) with delay/timing that varies enough to still collide
    with a single-shot read. Gives up after `attempts` and returns whatever
    the last read was, even if it still doesn't look right, rather than
    blocking forever."""
    reading = ""
    for _ in range(attempts):
        link.drain(drain_s)
        reading = (link.send(opencat.PRINT_VOLTAGE) or "").strip()
        if reading.startswith("Voltage"):
            return reading
    return reading


_RULE = "=" * 60


def _announce(i: int, total: int, name: str, kind: str, token: str, *,
              lead_s: float, bell: bool) -> None:
    """Print an unmissable, numbered header for the move about to run, with a
    beat of lead time (and an optional terminal bell) before it actually
    fires -- so if you're watching the robot instead of the screen, you get a
    cue to look up before it moves, not just a line of text after the fact."""
    print(f"\n{_RULE}\n[{i}/{total}]  {name}  ({kind})  ->  {token}\n{_RULE}")
    if bell:
        print("\a", end="", flush=True)
    if lead_s > 0:
        print(f"  starting in {lead_s:g}s...")
        time.sleep(lead_s)


def _allmoves(link: SerialLink, *, hold: float, recovery_hold: float,
              skip_recovery: bool, skip_gaits: bool = False,
              announce_s: float = 1.5, bell: bool = True) -> None:
    """Cycle every named movement G2 knows, reading back battery voltage
    (against a logged idle baseline, so a reviewer sees sag, not just an
    absolute number) and the reply latency after each one, logging both to
    the diag session -- so a review afterward can spot a move that drew
    unusually hard, replied slow (heading toward the link's read-timeout,
    a early sign of a move going non-responsive), or got no reply at all,
    not just what looked wrong live. Each move gets a numbered, ruled-off
    announcement with a lead-time pause (+ a terminal bell) before it fires,
    so which move is currently running is never ambiguous while watching the
    robot rather than the screen. The recovery/get-up keyframes (self-right,
    roll, drop-recover) get their own confirm before that section, since they
    move the body through its full range -- this pass logs voltage/latency
    for them same as everything else, but NOT whether the body actually ended
    up upright; that needs the IMU stream, whose line format --probe-imu
    (step 13a) hasn't confirmed yet at this point in the runbook, so it isn't
    wired in here. Always ends at `d` (rest)."""
    moves = _all_moves()
    skip_kinds = {"recovery"} if skip_recovery else set()
    if skip_gaits:
        skip_kinds |= {"gait", "carpet"}
    total = sum(1 for _, _, kind in moves if kind not in skip_kinds)
    print(f"Cycling {total} known moves ({hold:g}s hold each; recovery "
         f"keyframes get {recovery_hold:g}s and a confirm first)."
         + (" Gaits/carpet-walk skipped." if skip_gaits else "") + "\n")

    t0 = time.perf_counter()
    baseline = _read_voltage(link)
    diag.event("check_serial", "INFO", "sweep.baseline", voltage=baseline,
              elapsed_s=round(time.perf_counter() - t0, 3))
    if baseline:
        print(f"idle baseline battery: {baseline}\n")

    warned = False
    done = 0
    try:
        for name, token, kind in moves:
            if kind in ("gait", "carpet") and skip_gaits:
                continue
            if kind == "recovery":
                if skip_recovery:
                    continue
                if not warned:
                    warned = True
                    choice = input("\nNext: the recovery/get-up keyframes (self-right, "
                                  "roll-from-supine, drop-recover) -- these move the body "
                                  "through its full range. Continue? [Enter/q] "
                                  ).strip().lower()
                    if choice == "q":
                        break
            done += 1
            _announce(done, total, name, kind, token, lead_s=announce_s, bell=bell)
            link.send(token, read_reply=False)
            hold_s = recovery_hold if kind == "recovery" else hold
            print(f"  running -- watch now ({hold_s:g}s)")
            time.sleep(hold_s)
            # The move command was sent with read_reply=False, so whatever the
            # firmware echoed/printed for it is still sitting unread -- and
            # some skills print an extra debug line (`imuException: 0`) with
            # enough timing variance that one drain pass doesn't always clear
            # it either (confirmed on real hardware 2026-09-28). _read_voltage
            # drains-and-retries past either, instead of trusting one line.
            t0 = time.perf_counter()
            voltage = _read_voltage(link)
            elapsed = round(time.perf_counter() - t0, 3)
            diag.event("check_serial", "INFO", "move.done",
                      move=name, token=token, kind=kind, voltage=voltage,
                      elapsed_s=elapsed)
            if voltage:
                print(f"      battery: {voltage}  ({elapsed:g}s reply)")
            else:
                print(f"      (no reply, {elapsed:g}s -- board may have gone unresponsive)")
    finally:
        link.send(opencat.REST, read_reply=False)
        print("\nsent 'd' (rest) -- allmoves sweep done. "
             "Review the diag session's events.jsonl for the per-move voltage "
             "and reply-latency log.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="pi_pipeline.link.check_serial")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports")
    sub.add_parser("ping")
    p_send = sub.add_parser("send"); p_send.add_argument("command")
    bu = sub.add_parser("burst")
    bu.add_argument("token", help="serial token to run, e.g. kwkR")
    bu.add_argument("--seconds", type=float, default=1.5,
                    help="how long to run before auto-rest")
    sk = sub.add_parser("skills"); sk.add_argument("--hold", type=float, default=2.5)
    sub.add_parser("rest")
    sub.add_parser("feedback")
    fm = sub.add_parser("firstmove")
    fm.add_argument("--deg", type=float, default=15.0, help="degrees to nudge each joint")
    fm.add_argument("--walk-s", type=float, default=2.0, help="seconds to run wkF before auto-rest")
    am = sub.add_parser("allmoves")
    am.add_argument("--hold", type=float, default=2.5, help="seconds to hold each move")
    am.add_argument("--recovery-hold", type=float, default=4.0,
                    help="seconds to hold each recovery keyframe (they're longer sequences)")
    am.add_argument("--skip-recovery", action="store_true",
                    help="skip the self-right / roll / drop-recover keyframes")
    am.add_argument("--skip-gaits", action="store_true",
                    help="skip continuous locomotion gaits (walk/trot/crawl) + carpet-walk")
    am.add_argument("--announce-s", type=float, default=1.5,
                    help="pause after announcing a move, before it fires -- "
                         "time to look up from the terminal to the robot")
    am.add_argument("--no-bell", action="store_true",
                    help="skip the terminal bell before each move")
    args = ap.parse_args()

    with diag.session("check_serial", extra={"cmd": args.cmd}):
        if args.cmd == "ports":
            found = SerialLink.list_ports()
            for dev, desc in found:
                print(f"  {dev}  {desc}")
            print(f"  configured: {settings.serial_port} @ {settings.serial_baud}")
            if not found:
                print("  (none -- pyserial missing, or no adapters connected)")
            return

        link = _link()
        if not link.connect():
            print(f"could not open {settings.serial_port}")
            return
        try:
            if args.cmd == "ping":
                print("banner:", link.drain(1.0) or "(silent)")
                print("query :", link.send(opencat.QUERY) or "(no reply)")
            elif args.cmd == "send":
                if not opencat.is_safe(args.command):
                    print(f"refusing unsafe command {args.command!r}")
                    return
                print("reply:", link.send(args.command) or "(no reply)")
            elif args.cmd == "burst":
                if not opencat.is_safe(args.token):
                    print(f"refusing unsafe command {args.token!r}")
                    return
                _burst(link, args.token, args.seconds)
            elif args.cmd == "skills":
                for name, sk_ in skillcat.SKILLS.items():
                    cmd = skillcat.serial_command(name)
                    print(f"  {name:14} -> {cmd}")
                    link.send(cmd, read_reply=False)
                    time.sleep(args.hold)
                link.send(opencat.REST, read_reply=False)
            elif args.cmd == "rest":
                link.send(opencat.REST, read_reply=False)
                print("sent 'd' (rest)")
            elif args.cmd == "feedback":
                _feedback_check(link)
            elif args.cmd == "firstmove":
                _firstmove(link, deg=args.deg, walk_s=args.walk_s)
            elif args.cmd == "allmoves":
                _allmoves(link, hold=args.hold, recovery_hold=args.recovery_hold,
                         skip_recovery=args.skip_recovery, skip_gaits=args.skip_gaits,
                         announce_s=args.announce_s, bell=not args.no_bell)
        finally:
            link.close()


if __name__ == "__main__":
    main()
