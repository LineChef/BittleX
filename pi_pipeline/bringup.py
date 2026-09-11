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
never auto-executed here -- calibration (`c16`) and anything that walks or
gets the robot up should happen with your hands free to catch it, not from
inside this script's confirm prompt.
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
        Step("1", "Assembly & mechanical", "Assemble Bittle X V2",
            "Check servo calibration -- it ships calibrated; only fine-tune if "
            "movement looks off once it's together."),
        Step("2", "Assembly & mechanical", "Weigh the final build",
            "Weigh the whole build on a kitchen scale with the Pi + PiSugar S + "
            "camera + mount actually on it. Weigh the camera cluster and the "
            "PiSugar S battery SEPARATELY (the battery is more than half the "
            "current spine estimate). Balance each piece on an edge for height "
            "+ fore/aft center of mass. If the total is meaningfully off the "
            "~76 g estimate, update PAYLOAD_MASS_*/HEAD_MASS_* in "
            "opencat_gym_env.py and retrain or --finetune-lr "
            "(docs/rl/hardware-gated-backlog.md H2)."),
        Step("3", "Assembly & mechanical", "Range-of-motion pass + firmware calibration",
            "On the calibration stand, BEFORE it touches the ground: a full "
            "range-of-motion pass by hand (watch for binding / leg-on-leg "
            "collision), then firmware `c16` auto joint calibration. "
            "NOTE: this tool refuses calibration commands by design "
            "(opencat.is_safe blocks the 'c'/'cd' prefixes) -- send c16 "
            "through Petoi's own app or a raw serial terminal, not through "
            "check_serial. Once joints move safely by hand, "
            "`python -m pi_pipeline.link.check_serial firstmove` walks a "
            "guided one-joint-at-a-time check + a single confirmed step, "
            "before anything free-runs. Detailed steps: "
            "docs/guides/gait-deployment.md step 6."),
        Step("4", "Assembly & mechanical", "Wire Pi <-> BiBoard",
            "Data-only: RX/TX/GND (crossed), GND-GND. Leave the Pi's 5V pin "
            "unconnected -- PiSugar S is the sole power source. Confirm the "
            "back cover still fits. Connectors: docs/guides/pi-bring-up.md #0."),
        Step("5", "Serial link", "Find the serial port",
            "List ports, then set G2_SERIAL_PORT in .env (likely /dev/ttyS0 -> "
            "/dev/ttyAMA0 after disable-bt).",
            cmd=[py, "-m", "pi_pipeline.link.check_serial", "ports"]),
        Step("6", "Serial link", "Enable Serial-2 on the BiBoard",
            "Send `XS` (or edit OpenCat.h + reflash) so the board talks to the "
            "Pi over UART2. This can change which connection carries the "
            "reply, so it's shown here rather than auto-run: "
            "python -m pi_pipeline.link.check_serial send XS",
            manual_cmd="python -m pi_pipeline.link.check_serial send XS"),
        Step("7", "Serial link", "Confirm the board responds",
            "A passive handshake first (safe, nothing moves):",
            cmd=[py, "-m", "pi_pipeline.doctor", "--serial"]),
        Step("7b", "Serial link", "First movement: balance, then the skill set",
            "Only after step 3's calibration and with the robot somewhere safe "
            "to move -- these two commands are shown, not auto-run:\n"
            "  python -m pi_pipeline.link.check_serial send kbalance\n"
            "  python -m pi_pipeline.link.check_serial skills",
            manual_cmd="python -m pi_pipeline.link.check_serial send kbalance"),
        Step("8", "Voice", "Claude + memory end-to-end",
            "Text mode first -- the API key is already set.",
            cmd=[py, "-m", "pi_pipeline.voice", "--mode", "text"]),
        Step("9", "Voice", "Audio on the Pi's mic/speaker",
            "Tune G2_WAKE_WORD / G2_STT_SILENCE_S against the real mic, then "
            "try the full loop: "
            "python -m pi_pipeline.voice --mode voice --actuator serial"),
        Step("10", "Voice", "Benchmark the voice stack on the real Pi",
            "Confirms en_US-ryan-low + Vosk hit real-time on 512 MB. If "
            "sluggish: shorter CLAUDE_MAX_TOKENS, streaming TTS, a longer "
            "'thinking' cue.",
            cmd=[py, "-m", "pi_pipeline.benchmark_pi"]),
        Step("11", "RL sim-to-real", "Real-time joint control bench",
            "Sim bench was 0.43 ms/step -- confirm on the real Pi. Shown, not "
            "auto-run (drives real servos): "
            "python pi_pipeline/gait/bench_real.py",
            manual_cmd="python pi_pipeline/gait/bench_real.py"),
        Step("12", "RL sim-to-real", "The H1 head-to-head",
            "run_gait.py --probe-imu (confirm the IMU format) -> --openloop "
            "(verify servo signs) -> --cmd (the learned gait) -> the H1 "
            "head-to-head vs firmware kwkF. Methodology + decision rule: "
            "docs/rl/h1-rubric.md; h1_score.py produces the verdict. Shown, "
            "not auto-run: python pi_pipeline/gait/run_gait.py --probe-imu",
            manual_cmd="python pi_pipeline/gait/run_gait.py --probe-imu"),
        Step("13", "Vision on the robot", "Mount the camera, train the edge classifier",
            "Train the desk-edge classifier on the real mounted POV (B16 -- "
            "highest priority), wire Avoider decisions to the actuator, build "
            "the CliffGuard reflex against the trained classifier."),
        Step("14", "Integration", "Voice + vision + memory concurrently",
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


def _run_interactive(steps: list, done: set) -> None:
    for step in steps:
        _print_step(step, done=step.id in done)
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
