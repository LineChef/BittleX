"""The hardware A/B for falls at transitions (user, 2026-11-06). Runs ONLY on the user's go, on hardwood, hands near, the voice service stopped (like claw_look).

A cycle is the transitions that logged falls were made of, back to back: attention pose, a full claw look, the back-legs-first stand-up, a firmware turn and at once a turn the other way, with a stop after each. One variant per run:

    baseline   no gate, no calm stop (what the code did)       calm   the stop waits for a calm moment        gate   the pose gate before the turn        both
    python -m pi_pipeline.behavior.transition_drill --variant calm --cycles 10

The run ends at the first fall (he is then picked up by hand and the round is reported). Result: cycles completed, falls, the worst tilt swing, how often the gate re-seated. Compare variants
by cycles-to-fall and swing; the approach is written into the project guidelines only after one variant shows it clearly beats the baseline (docs/guides/falls-at-transitions.md, not yet written).
"""
from __future__ import annotations

import time

# name -> (calm stop, pose gate, whole-cycle stop, pre-position, eased stop). One lever at a time against baseline; the first two are the 2026-11-06 guards, the last two the firmware-reading levers.
VARIANTS = {"baseline": (False, False, False, False, False), "calm": (True, False, False, False, False), "gate": (False, True, False, False, False), "both": (True, True, False, False, False),
            "cycle": (False, False, True, False, False), "pre": (False, False, False, True, False), "cycle_pre": (False, False, True, True, False), "eased": (False, False, False, False, True)}


NEAR_FALL_DEG = 20.0      # a tilt swing this big in one phase counts as a near fall (most falls are never recorded, so variants are compared on swings too)


STANDUP_FELL_SWING_DEG = 30.0   # a stand-up whose tilt swung this much is a fall even if the tilt never reached the fall limit (2026-11-07: a leg-out stand-up was not seen and the drill kept driving him)
TURN_S = 1.5                    # a turn's length: with the measured gait periods (1.00 s left, 1.04 s right) a 1.0 s turn was already one whole cycle, so the whole-cycle stop had nothing to do


def run_variant(robot, cycles: int, *, turn_deg: float = 25.0, turn_s: float = TURN_S, look=None, say=print, sleep=time.sleep, turns_only: bool = False) -> dict:
    """`cycles` of the pattern the logged falls follow, with no rest between cycles: attention pose, a full claw look (arm up, left, right, centre, down), the back-legs-first stand-up, a turn, and at
    once a turn back the other way. Stops at the first fall. `look(robot)` makes the claw look (default: claw_survey.run_claw_look without pictures). Returns
    {"cycles", "fell", "fell_at", "worst_swing_deg", "near_falls", "reseats"}. `turns_only` skips the attention pose, the claw look and the stand-up from it: he stands once and then only turns and turns
    back, so the turn and stop levers are tested where they act (2026-11-07: most rounds ended at the stand-up before a lever could matter)."""
    if look is None:
        from . import claw_survey
        look = lambda r: claw_survey.run_claw_look(r._lk, None, "drill", stopped=r.fallen)      # noqa: E731
    worst, near, done, fell = 0.0, 0, 0, False
    fell_at = ""

    legs_off: list = []

    def trace(phase: str) -> None:
        """The IMU tilt through a phase (pitch / roll min and max, and the last readings), so a fall leaves something to read."""
        p, r = list(getattr(robot, "_pitch", []) or []), list(getattr(robot, "_roll", []) or [])
        if p and r:
            say(f"   {phase} tilt: pitch {min(p):+.0f}..{max(p):+.0f}, roll {min(r):+.0f}..{max(r):+.0f}; last pitch {[round(x) for x in p[-6:]]} roll {[round(x) for x in r[-6:]]}")

    def note(phase: str) -> None:
        nonlocal worst, near
        sw = robot.swing_deg()
        worst = max(worst, sw)
        if sw >= NEAR_FALL_DEG:
            near += 1
        say(f"   {phase}: swing {sw:.0f} deg")
        trace(phase)
        bad = getattr(robot, "last_leg_check", None)
        if phase.startswith("stand-up") and bad:
            legs_off.append(bad)
            say(f"   LEGS OFF their stand angle after the stand-up: {bad}")

    if hasattr(robot, "imu_alive") and not robot.imu_alive():
        say("NO IMU FRAMES: the board is silent, the guards would do nothing. Check the Pi-to-BiBoard plug and the board's power. Round not run.")
        return {"cycles": 0, "fell": False, "worst_swing_deg": 0.0, "near_falls": 0, "reseats": 0, "stand_ups_with_legs_off": 0, "void": "no IMU frames"}
    if turns_only and robot.stand_up() == "fell":
        return {"cycles": 0, "fell": True, "fell_at": "first stand-up", "worst_swing_deg": 0.0, "near_falls": 0, "reseats": 0, "stand_ups_with_legs_off": 0}
    for i in range(cycles):
        side = 1 if i % 2 == 0 else -1
        if not turns_only:
            r_state = robot.relax()
            trace("attention pose")
            if r_state != "ok" or robot.fallen():                         # a fall anywhere ends the round at once: nothing more is sent to a fallen G2
                trace("fall in the attention pose")
                fell, fell_at = True, "attention pose"
                break
            look(robot)
            trace("claw look")
            if hasattr(robot, "imu_alive") and i > 0 and not getattr(robot, "_pitch", None):
                say("NO IMU FRAMES during the round: void.")
                return {"cycles": done, "fell": False, "worst_swing_deg": round(worst, 1), "near_falls": near, "reseats": robot.gate_reseats, "stand_ups_with_legs_off": len(legs_off), "void": "IMU went silent"}
            if robot.fallen():
                trace("fall")
                fell, fell_at = True, "claw look"
                break
            if robot.stand_up_from_attention() == "fell":
                fell, fell_at = True, "stand-up from attention"
                break
            note("stand-up from attention")
            if robot.swing_deg() >= STANDUP_FELL_SWING_DEG:
                say(f"   the stand-up swung {robot.swing_deg():.0f} deg: counted as a fall, nothing more is sent")
                fell, fell_at = True, "stand-up from attention (swing)"
                break
        for k, deg in enumerate((side * turn_deg, -side * turn_deg)):
            state = robot.turn(deg, turn_s)
            note(f"turn {'right' if deg > 0 else 'left'}")
            for what in ("last_preposition", "last_cycle_stop", "last_eased_stop"):
                if getattr(robot, what, None):
                    say(f"   {what.replace('_', ' ')}: {getattr(robot, what)}")
            le = getattr(getattr(robot, "_lk", None), "last_ease", None)
            if le:
                say(f"   link transition: {le}")
            if state == "fell":
                fell, fell_at = True, f"turn {'right' if deg > 0 else 'left'}"
                break
        say(f"cycle {i + 1}/{cycles}: {'FELL' if fell else 'ok'}, re-seats so far {robot.gate_reseats}")
        if fell:
            break
        done += 1
    return {"cycles": done, "fell": fell, "fell_at": fell_at, "worst_swing_deg": round(worst, 1), "near_falls": near, "reseats": robot.gate_reseats, "stand_ups_with_legs_off": len(legs_off)}


def run_stand_only(robot, cycles: int, *, say=print, sleep=time.sleep, rest_s: float = 2.5, watch_s: float = 1.5) -> dict:
    """Stand up from rest `cycles` times (rest, then the stand-up under test, then the tilt for `watch_s` seconds), nothing else: the stand-up on its own (2026-11-08: it tipped him over toward the side whose
    legs rose later; is it the firmware stand-up, the gyro balance being off, or the Pi's sequenced rise?). The stand-up is whatever the switches say (`G2_STAND_VIA`, `G2_GYRO_BALANCE`). Stops at the first fall
    (nothing is sent to a fallen G2). Returns {"cycles", "fell", "fell_at", "worst_swing_deg", "near_falls", "swings"}."""
    lk = robot._lk
    worst, near, swings, fell = 0.0, 0, [], False
    done, vmins, poses = 0, [], []
    try:
        from ..power import battery
        volt_read = lambda link: battery.read_voltage(link, attempts=1, drain_s=0.0)      # noqa: E731
    except Exception:  # noqa: BLE001
        volt_read = None
    for i in range(cycles):
        lk.send("krest", read_reply=False, settle=0.0)
        sleep(rest_s)
        lk.send("gP", read_reply=False, settle=0.0)
        sleep(0.3)
        robot._pitch, robot._roll = [], []
        lk.send("kbalance", read_reply=False, settle=0.0)            # the stand-up under test
        t_end = robot._clock() + watch_s
        volts, next_v = [], robot._clock()
        while robot._clock() < t_end and not fell:
            fell = robot._fell()
            if robot._clock() >= next_v and callable(volt_read):
                next_v = robot._clock() + 0.3                         # the pack during the rise: a servo that sags may be a voltage dip (best effort: a read can fail while the IMU streams)
                try:
                    v = volt_read(lk)
                    if v is not None:
                        volts.append(v)
                except Exception:  # noqa: BLE001
                    pass
            sleep(0.05)
        sw = robot.swing_deg()
        swings.append(round(sw, 1))
        worst = max(worst, sw)
        if sw >= NEAR_FALL_DEG:
            near += 1
        lk.send("gp", read_reply=False, settle=0.0)
        pose = "?"
        try:
            from . import ball_chase as _bc
            j = _bc.read_joints(lk, timeout_s=1.0)
            pose = _bc.classify_pose(j) if j else "?"
        except Exception:  # noqa: BLE001
            pass
        poses.append(pose)
        lk.send("gb", read_reply=False, settle=0.0)                  # the gyro balance back off after each stand-up (it may have been switched on for it): never left on at rest or in the attention pose, where the board took the pose for a fall
        if pose not in ("stand", "?"):
            say(f"   NOT STANDING: the board reads the pose as {pose!r} (a stand-up the board ignored or did not finish)")
        vmins.append(round(min(volts), 2) if volts else None)
        say(f"stand-up {i + 1}/{cycles}: swing {sw:.0f} deg" + (" FELL" if fell else "") + (f", pack during the rise: min {min(volts):.2f} V of {len(volts)} reads" if volts else ", pack during the rise: no reading"))
        trace_p, trace_r = list(robot._pitch), list(robot._roll)
        if trace_p and trace_r:
            say(f"   tilt: pitch {min(trace_p):+.0f}..{max(trace_p):+.0f}, roll {min(trace_r):+.0f}..{max(trace_r):+.0f}")
        if sw >= STANDUP_FELL_SWING_DEG:
            fell = True
        if fell:
            break
        done += 1
    return {"cycles": done, "fell": fell, "fell_at": "stand-up from rest" if fell else "", "worst_swing_deg": round(worst, 1), "near_falls": near, "swings": swings, "min_volts": vmins, "poses": poses}


MEASURE_GAITS = ("kwkL", "kwkR", "kwkF", "kbkF")
MEASURE_S = 4.0


def measure(robot, *, say=print, seconds: float = MEASURE_S) -> dict:
    """Each gait for `seconds` from the stand, the IMU recorded, the cycle time found by autocorrelation and saved (gait_cycle.save). Stops at the first fall."""
    from . import gait_cycle
    out = {}
    for token in MEASURE_GAITS:
        if robot.fallen():
            say("fell: measuring stopped")
            break
        state = robot._skill(token, seconds)
        stamps, rolls, pitches = robot.last_move_imu
        n = len(stamps)
        est = gait_cycle.estimate(stamps, rolls, pitches) if n else None
        rate = (n / (stamps[-1] - stamps[0])) if n > 1 and stamps[-1] > stamps[0] else 0.0
        if est:
            gait_cycle.save(token, est[0], est[1], n)
            say(f"{token}: period {est[0]:.2f} s (strength {est[1]:.2f}), {n} IMU frames at {rate:.0f}/s, {state}")
            out[token] = est
        else:
            say(f"{token}: no clear cycle ({n} IMU frames at {rate:.0f}/s), {state}")
        if state == "fell":
            break
        robot._sleep(2.0)
    return out


def main() -> None:
    import argparse

    from . import ball_chase as chase
    ap = argparse.ArgumentParser(description="Falls at transitions: one A/B variant.")
    ap.add_argument("--variant", choices=sorted(VARIANTS))
    ap.add_argument("--measure", action="store_true", help="measure each gait's cycle time from the IMU (no variant; writes ~/.local/share/g2/gait_cycles.json)")
    ap.add_argument("--cycles", type=int, default=10)
    ap.add_argument("--turns-only", action="store_true", help="stand once, then only turn and turn back (no attention pose, claw look or stand-up from it): tests the turn and stop levers where they act")
    ap.add_argument("--stand-only", action="store_true", help="only stand up from rest, --cycles times (the stand-up on its own; G2_STAND_VIA and G2_GYRO_BALANCE choose what is under test)")
    ap.add_argument("--turn-s", type=float, default=TURN_S, help=f"each turn's length in seconds (default {TURN_S})")
    args = ap.parse_args()
    if not args.measure and not args.variant:
        ap.error("--variant or --measure is required")
    # (--measure takes no variant: it runs with every lever off, which is the baseline)
    chase.STOP_CALM, chase.POSE_GATE, chase.CYCLE_STOP, chase.PREPOSITION, chase.EASED_STOP = VARIANTS[args.variant or "baseline"]
    import subprocess
    try:                                                        # 2026-11-07: the voice service was running beside the drill for 25 minutes and shared the serial port; refuse to start with it up
        up = subprocess.run(["systemctl", "is-active", "g2-voice"], capture_output=True, text=True, timeout=5).stdout.strip() == "active"
    except Exception:  # noqa: BLE001
        up = False
    if up:
        print("the g2-voice service is RUNNING: it shares the BiBoard's serial port with this drill. Stop it first (sudo systemctl stop g2-voice). Round not run.")
        return
    from ..link.serial_link import SerialLink
    from ..power import battery
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    import logging
    board_moves: list = []

    class _Watch(logging.Handler):                      # the BiBoard's own voice module starting a move (a spoken word, a TV): that round is void, not a fall caused by the transitions
        def emit(self, record):
            msg = record.getMessage()
            if "started a move the Pi did not send" in msg and "'balance'" not in msg:       # (a late echo of the Pi's own kbalance, about 3 s after it, was flagged on every round of 2026-11-07)
                board_moves.append(msg[-60:])
    logging.getLogger("g2.command_log").addHandler(_Watch())
    logging.getLogger().addHandler(_Watch())
    robot = chase.SerialRobot(link, fall_deg=30.0)          # 30 deg off level is not standing (the stand-ups that fell on 2026-11-07 stayed under the old 45 deg limit)
    fell = False
    try:
        if args.stand_only:
            res = run_stand_only(robot, args.cycles)
            fell = bool(res.get("fell"))
            print("RESULT", args.variant + "+stand_only", res)
            return
        chase._stand_if_lying(link, "kbalance")
        if args.measure:
            measure(robot)
            return
        res = run_variant(robot, args.cycles, turn_s=args.turn_s, turns_only=args.turns_only)
        fell = bool(res.get("fell"))
        if board_moves:
            res["void"] = f"the board started a move on its own during the round: {board_moves[-1]}"
        print("RESULT", args.variant + ("+turns_only" if args.turns_only else ""), res)
    except KeyboardInterrupt:
        print("ended")
    finally:
        if not fell:                                    # nothing is sent to a G2 that fell: a rest command to one lying with a leg out dropped him again (2026-11-07)
            try:
                link.send("krest", read_reply=False, settle=0.0)
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    main()
