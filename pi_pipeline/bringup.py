"""`python -m pi_pipeline.bringup` -- the ordered hardware bring-up sequence
from `docs/project-plan.md` ("When the hardware arrives"), as a guided,
resumable checklist instead of a doc you re-read and lose your place in.

    python -m pi_pipeline.bringup            # resume where you left off
    python -m pi_pipeline.bringup --list     # just print every step, no interaction
    python -m pi_pipeline.bringup --restart  # clear saved progress, start over
    python -m pi_pipeline.bringup --from 5   # jump to a step regardless of progress

At each step: `Enter` checks it off and moves on, `r` runs the suggested
command right here (only offered for read-only / passive commands -- ports
list, `doctor`, a ping, a voltage read; nothing that moves a joint), `s` skips
it, `q` quits and saves your place. Progress is written to
`<G2_STATE_DIR or ~/.local/share/g2>/bringup_progress.json` so this is safe to
stop and resume across sessions -- and across days.

Movement commands are always shown as text to run yourself in another shell,
never auto-executed here -- calibration (`c`) and anything that walks or
gets the robot up should happen with your hands free to catch it, not from
inside this script's confirm prompt.

STAY ON THE CALIBRATION STAND THROUGH STEP 13a. Servo sign, the real IMU
format, and payload weight are all unknown until the real robot is in hand;
on the stand, getting any of them wrong is a flailing leg, not a fall or a
walk off an edge. The floor is earned once step 13a's --openloop confirms the
servo signs are right -- that's the one check that genuinely needs ground
contact (step 13b, the H1 head-to-head).

Steps 1-3 are Phase 0: bare Bittle X + BiBoard only, nothing Pi/PiSugar/
camera related -- deliberately rules out mechanical/servo/BiBoard problems
before the Pi is ever wired in. Step 3 talks to BiBoard over its own USB
port (temporarily set G2_SERIAL_PORT to that, not the eventual Pi port).
Steps 4 onward are Phase 1+, gated on the Pi being physically wired to the
frame -- step 8 re-runs the same serial checks as step 3, now through the
Pi, specifically so the two sessions' event logs can be diffed for a
voltage/latency delta from adding the Pi stack. Step IDs here match
docs/project-plan.md's "When the hardware arrives" numbering exactly --
keep the two in sync if either changes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Step:
    id: str
    section: str
    title: str
    body: str
    cmd: list | None = None       # a safe, read-only command this script may run
    manual_cmd: str | None = None  # a command to show but never auto-run (moves the robot)


def _steps() -> list[Step]:
    py = sys.executable
    return [
        # --- Phase 0: bare Bittle X + BiBoard, no Pi in the loop ---
        Step("1", "Assembly & mechanical (Phase 0)", "Assemble Bittle X V2",
            "Match joints to the bootup posture in Petoi's unboxing diagram "
            "BEFORE the first power-on (bittle-x.petoi.com/2-open-the-box), "
            "not just whatever position they happen to sit in. Pre-assembled "
            "units ship only COARSE-tuned per Petoi's own docs -- plan on "
            "doing step 2's calibration pass, not skipping it. If a joint "
            "feels stuck/weak despite a correct command, that's likely tight "
            "new-gear protection kicking in, not a fault -- rotate it by "
            "hand with moderate resistance first. Route the neck cable "
            "knee-side to shoulder-side to avoid pinching. Full research: "
            "docs/hardware/calibration-and-bringup-research.md."),
        Step("2", "Assembly & mechanical (Phase 0)", "Range-of-motion pass + firmware calibration",
            "ON THE STAND, BEFORE it touches the ground -- and stay there "
            "through step 13a (see the rule at the top of this list): a full "
            "range-of-motion pass by hand (watch for binding / leg-on-leg "
            "collision), then firmware calibration (bare `c` per Petoi's "
            "docs, not `c16` -- verify the real token once serial is up). "
            "If serial/app access isn't working yet, calibration mode can "
            "also be entered by powering on with the robot tilted one side "
            "up (auto-trigger on 2022+ units, which covers Bittle X V2). "
            "NOTE: this tool refuses calibration commands by design "
            "(opencat.is_safe blocks the 'c'/'cd' prefixes) -- send it "
            "through Petoi's own app or a raw serial terminal, not through "
            "check_serial. Once joints move safely by hand, step 3's "
            "`firstmove` walks a guided one-joint-at-a-time check + a single "
            "confirmed step, before anything free-runs. Detailed steps: "
            "docs/guides/gait-deployment.md step 6."),
        Step("3a", "Serial link (Phase 0, BiBoard USB, no Pi)", "Find the serial port",
            "STILL ON THE STAND, no Pi wired -- talk to BiBoard over its own "
            "USB port. List ports, then TEMPORARILY set G2_SERIAL_PORT in "
            ".env to that port (you'll point it back at the Pi in step 6).",
            cmd=[py, "-m", "pi_pipeline.link.check_serial", "ports"]),
        Step("3b", "Serial link (Phase 0, BiBoard USB, no Pi)", "First movement: balance, then the skill set",
            "Only after step 2's calibration is clean -- these commands are "
            "shown, not auto-run:\n"
            "  python -m pi_pipeline.link.check_serial firstmove\n"
            "  python -m pi_pipeline.link.check_serial send kbalance\n"
            "  python -m pi_pipeline.link.check_serial skills",
            manual_cmd="python -m pi_pipeline.link.check_serial firstmove"),
        Step("3c", "Serial link (Phase 0, BiBoard USB, no Pi)", "Full movement sweep -- every known move, ON THE STAND",
            "Cycles EVERY move G2 knows (voice skills + the autonomous-behaviour "
            "gestures + sleep + carpet gait + the recovery/get-up keyframes, "
            "which nothing else exercises), reading back battery voltage after "
            "each one and logging it to the diag session. This is the actual "
            "'base hardware ruled out' checkpoint -- note this session's ID "
            "(~/g2_logs/<session_id>/) as the pre-Pi baseline to diff against "
            "once step 8c re-runs this same sweep through the Pi. Confirms "
            "separately before the recovery keyframes (they move the body "
            "through its full range). Shown, not auto-run: "
            "python -m pi_pipeline.link.check_serial allmoves\n"
            "(In parallel, off-frame: bench dry-fit the Pi + PiSugar + clip "
            "assembly independently -- docs/build/biboard-pi-connector.md.)",
            manual_cmd="python -m pi_pipeline.link.check_serial allmoves"),
        # --- Phase 1+: the Pi is now physically wired to the frame ---
        Step("4", "Assembly & mechanical (Phase 1)", "Weigh the final build",
            "Weigh the whole build on a kitchen scale with the Pi + PiSugar S + "
            "camera + mount actually on it. Weigh the camera cluster and the "
            "PiSugar S battery SEPARATELY (the battery is more than half the "
            "current spine estimate). Balance each piece on an edge for height "
            "+ fore/aft center of mass. If the total is meaningfully off the "
            "~76 g estimate, update PAYLOAD_MASS_*/HEAD_MASS_* in "
            "opencat_gym_env.py and retrain or --finetune-lr "
            "(docs/rl/hardware-gated-backlog.md H2)."),
        Step("5", "Assembly & mechanical (Phase 1)", "Wire Pi <-> BiBoard",
            "Data-only: RX/TX/GND (crossed), GND-GND. Leave the Pi's 5V pin "
            "unconnected -- PiSugar S is the sole power source. Confirm the "
            "back cover still fits. Connectors: docs/guides/pi-bring-up.md #0."),
        Step("6", "Serial link (Phase 5, via Pi)", "Find the serial port",
            "List ports, then set G2_SERIAL_PORT in .env BACK to the Pi's port "
            "(likely /dev/ttyS0 -> /dev/ttyAMA0 after disable-bt).",
            cmd=[py, "-m", "pi_pipeline.link.check_serial", "ports"]),
        Step("7", "Serial link (Phase 5, via Pi)", "Enable Serial-2 on the BiBoard",
            "Send `XS` (or edit OpenCat.h + reflash) so the board talks to the "
            "Pi over UART2. This can change which connection carries the "
            "reply, so it's shown here rather than auto-run: "
            "python -m pi_pipeline.link.check_serial send XS",
            manual_cmd="python -m pi_pipeline.link.check_serial send XS"),
        Step("8a", "Serial link (Phase 5, via Pi)", "Confirm the board responds",
            "A passive handshake first (safe, nothing moves):",
            cmd=[py, "-m", "pi_pipeline.doctor", "--serial"]),
        Step("8b", "Serial link (Phase 5, via Pi)", "First movement: balance, then the skill set -- again, now through the Pi",
            "ON THE STAND. Same commands as step 3b, now routed through the "
            "Pi instead of BiBoard's own USB -- shown, not auto-run:\n"
            "  python -m pi_pipeline.link.check_serial firstmove\n"
            "  python -m pi_pipeline.link.check_serial send kbalance\n"
            "  python -m pi_pipeline.link.check_serial skills",
            manual_cmd="python -m pi_pipeline.link.check_serial firstmove"),
        Step("8c", "Serial link (Phase 5, via Pi)", "Full movement sweep -- again, now through the Pi",
            "Same command as step 3c, now through the Pi's wiring -- diff "
            "this session's events.jsonl against the Phase 0 (step 3c) "
            "baseline for a voltage/latency delta from adding the Pi + "
            "PiSugar stack. Shown, not auto-run: "
            "python -m pi_pipeline.link.check_serial allmoves",
            manual_cmd="python -m pi_pipeline.link.check_serial allmoves"),
        Step("9", "Voice (Phase 7, still on the stand)", "Claude + memory end-to-end",
            "Text mode first -- the API key is already set.",
            cmd=[py, "-m", "pi_pipeline.voice", "--mode", "text"]),
        Step("10", "Voice (Phase 7, still on the stand)", "Audio on the Pi's mic/speaker",
            "Tune G2_WAKE_WORD / G2_STT_SILENCE_S against the real mic, then "
            "try the full loop: "
            "python -m pi_pipeline.voice --mode voice --actuator serial"),
        Step("11", "Voice (Phase 7, still on the stand)", "Benchmark the voice stack on the real Pi",
            "Confirms en_US-ryan-low + Vosk hit real-time on 512 MB. If "
            "sluggish: shorter CLAUDE_MAX_TOKENS, streaming TTS, a longer "
            "'thinking' cue.",
            cmd=[py, "-m", "pi_pipeline.benchmark_pi"]),
        Step("12", "RL sim-to-real (Phase 6, still on the stand)", "Real-time joint control bench",
            "Sim bench was 0.43 ms/step -- confirm on the real Pi. Shown, not "
            "auto-run (drives real servos): "
            "python pi_pipeline/gait/bench_real.py",
            manual_cmd="python pi_pipeline/gait/bench_real.py"),
        Step("13a", "RL sim-to-real (Phase 6)", "IMU probe + servo-sign check -- STILL ON THE STAND",
            "This is the last stand-only step. The line FORMAT is now known "
            "from firmware source (MCU:/ICM: prefix, accel then negated "
            "yaw/pitch/roll -- parse_imu_line already updated) -- "
            "--probe-imu here is now confirming two things still genuinely "
            "unknown until real hardware: (1) which chip prefix this unit "
            "actually sends (MCU vs ICM), and (2) the real yaw sign (parsed "
            "as re-negated back to raw, unverified against an actual "
            "rotation -- rotate the robot and confirm the sign looks right, "
            "flip in parse_imu_line if backwards). Also a reminder: this "
            "stream is ACCELERATION, not gyro -- residual_policy.py needs "
            "real angular velocity, which stock firmware doesn't stream at "
            "all (see parse_imu_line's docstring) -- that's a separate, "
            "still-open decision, not something --probe-imu can resolve. "
            "--openloop then verifies each servo's sign against "
            "deploy_map.py's SERVO_SIGN. Do NOT move to the floor (step 13b) "
            "until --openloop looks right -- a flipped sign needs to be caught "
            "here, not mid-walk. Shown, not auto-run: "
            "python pi_pipeline/gait/run_gait.py --probe-imu",
            manual_cmd="python pi_pipeline/gait/run_gait.py --probe-imu"),
        Step("13b", "RL sim-to-real (Phase 6)", "The H1 head-to-head -- FIRST TIME ON THE FLOOR",
            "Only after 13a's --openloop confirms correct servo signs. "
            "--cmd (the learned gait) -> the H1 head-to-head vs firmware "
            "kwkF. Methodology + decision rule: docs/rl/h1-rubric.md; "
            "h1_score.py produces the verdict. Keep the emergency stop within "
            "reach (--halt, or say 'emergency stop') for the whole thing. "
            "Shown, not auto-run: python pi_pipeline/gait/run_gait.py --cmd 0.1\n"
            "ONCE H1 PASSES: rename run20m_ppo from its training-artefact name "
            "to a deployment name (one rename commit) -- don't defer this, it "
            "gets easy to forget once integration work starts.",
            manual_cmd="python pi_pipeline/gait/run_gait.py --cmd 0.1"),
        Step("13c", "RL sim-to-real (Phase 6)", "OPTIONAL, not blocking: servo-thermal bench calibration",
            "The thermal governor (gait/thermal_guard.py) has never seen real "
            "hardware -- every constant is a placeholder. Whenever convenient "
            "post-H1 (not blocking further bring-up): hold the robot in a "
            "fixed hard stance (or one leg against a stop) until protection "
            "trips, log the time and the cooldown curve, fit k_gen/k_diss/"
            "T_trip from that. Full procedure: docs/hardware/servo-thermal.md "
            "section 3 item 5 / section 4b's retuning checklist.",
            manual_cmd=None),
        Step("14", "Vision on the robot (Phase 8)", "Mount the camera, train the edge classifier",
            "Train the desk-edge classifier on the real mounted POV (B16 -- "
            "highest priority), wire Avoider decisions to the actuator, build "
            "the CliffGuard reflex against the trained classifier."),
        Step("15", "Integration (Phase 10)", "Voice + vision + memory concurrently",
            "Historically the messiest phase -- budget real time for timing/"
            "resource conflicts. Then revisit locomotion with perception in "
            "the loop toward the Phase 8 target capability."),
    ]


def _state_path() -> Path:
    base = os.environ.get("G2_STATE_DIR") or os.path.expanduser("~/.local/share/g2")
    return Path(base) / "bringup_progress.json"


def _load_progress() -> set:
    try:
        return set(json.loads(_state_path().read_text()).get("completed", []))
    except (OSError, ValueError):
        return set()


def _save_progress(done: set) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"completed": sorted(done)}, indent=2))


def _print_step(step: Step, *, done: bool) -> None:
    box = "[x]" if done else "[ ]"
    print(f"\n{box} step {step.id} -- {step.section}")
    print(f"    {step.title}")
    for line in step.body.splitlines():
        print(f"    {line}")
    if step.cmd:
        print(f"    $ {' '.join(step.cmd)}")
    if step.manual_cmd:
        print(f"    $ {step.manual_cmd}   (run this yourself -- not auto-run)")


_STAND_RULE = (
    "\n*** STAY ON THE CALIBRATION STAND THROUGH STEP 13a. ***\n"
    "Servo sign, the real IMU format, and payload weight are all unknown until\n"
    "now -- on the stand, getting one wrong is a flailing leg, not a fall. The\n"
    "floor is earned once 13a's --openloop confirms the servo signs (13b).\n"
)


def _run_interactive(steps: list, done: set) -> None:
    print(_STAND_RULE)
    for step in steps:
        _print_step(step, done=step.id in done)
        if step.id == "13b":
            confirm = input("\n  This is the FIRST FLOOR TEST. Did step 13a's "
                           "--openloop look correct? [y/N] ").strip().lower()
            if confirm != "y":
                print("  Stopping here -- go back to step 13a first.")
                _save_progress(done)
                return
        while True:
            prompt = "[Enter]=done"
            if step.cmd:
                prompt += "  r=run it"
            prompt += "  s=skip  q=quit: "
            choice = input(prompt).strip().lower()
            if choice == "q":
                _save_progress(done)
                print(f"Saved progress. Resume any time with "
                      f"`python -m pi_pipeline.bringup`.")
                return
            if choice == "s":
                break
            if choice == "r" and step.cmd:
                try:
                    subprocess.run(step.cmd, check=False)
                except (OSError, KeyboardInterrupt) as e:
                    print(f"  ({type(e).__name__}: {e})")
                continue   # re-show the prompt so they can check it done / move on
            # Enter, or anything else -- check it done and advance
            done.add(step.id)
            _save_progress(done)
            break
    print("\nAll steps done (or skipped). See docs/project-plan.md for what's next.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.bringup")
    ap.add_argument("--list", action="store_true", help="print every step, no interaction")
    ap.add_argument("--restart", action="store_true", help="clear saved progress")
    ap.add_argument("--from", dest="from_id", help="jump to a step id regardless of progress")
    args = ap.parse_args()

    steps = _steps()
    if args.list:
        print(_STAND_RULE)
        done = _load_progress()
        for step in steps:
            _print_step(step, done=step.id in done)
        return

    if args.restart:
        _save_progress(set())
        print("progress cleared")

    done = _load_progress()
    if args.from_id:
        ids = [s.id for s in steps]
        if args.from_id not in ids:
            raise SystemExit(f"no such step {args.from_id!r} -- try one of {ids}")
        steps = steps[ids.index(args.from_id):]

    _run_interactive(steps, done)


if __name__ == "__main__":
    main()
