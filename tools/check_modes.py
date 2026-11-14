#!/usr/bin/env python3
"""Mode consistency check (owner, 2026-11-13: "any change we make to G2 in any mode should apply to all modes ... not have mode specific behavior unless I explicitly ask for it").

A MODE is anything that runs G2: the voice service, the exploration, the ball chase and the goals, the test drills and scripts. What G2's BODY does (stand up, lie down, look with the claw, what a fall is, what
a deaf board is) is the same in every mode, so it is defined once (`pi_pipeline/body.py`, `behavior/ball_chase.py` standard moves, `behavior/claw_survey.py`, `gait/stand_guard.py`, `link/*`) and the modes
only call it. This script fails when a mode builds its own.

  BLOCKING (always an error)
    R1  a second claw look: a function named run_claw_look / claw_scan / claw_look_sequence defined outside behavior/claw_survey.py and behavior/ball_chase.py
    R2  a StandGuard built anywhere but the two mode entry points (voice/__main__.py, explore_session.py), or built without `on_fall=`
    R3  a fall threshold written as a number other than pi_pipeline/body.py's FALL_DEG (`fall_deg=` / `fall_abort_deg=`)
    R7  a `MODE-SPECIFIC(...)` exception in the code that docs/specification/mode-exceptions.md does not list (the owner's explicit request, with the date)
  RATCHET (known today, listed in tools/mode_check_baseline.json; a NEW one is an error, fixing one means removing it from the baseline)
    R4  a mode file sends a stand / rest / attention command itself (send("kup" | "kbalance" | "kcalib" | "krest" | "d")) instead of calling the standard move
    R5  a StandGuard built without `on_silent=` (a deaf board must end every mode the same way)

Run: python tools/check_modes.py [--list] [--update-baseline]   (also run by the pre-commit hook and by tests/test_mode_parity.py)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "pi_pipeline"
BASELINE = Path(__file__).resolve().parent / "mode_check_baseline.json"
EXCEPTIONS = ROOT / "docs" / "specification" / "mode-exceptions.md"

LOOK_HOME = {"behavior/claw_survey.py", "behavior/ball_chase.py"}
GUARD_ENTRY = {"voice/__main__.py", "explore_session.py"}
MODE_DIRS = ("behavior/", "voice/", "goals/", "app/")
MODE_FILES = {"explore_session.py", "punt_launch.py", "goal_launch.py"}
STANDARD_HOMES = {"behavior/ball_chase.py", "behavior/claw_survey.py"}            # the standard moves live here (SerialRobot: stand_up, sit_down, stand_from_sit, rest)
LOOK_NAMES = re.compile(r"^\s*def\s+(run_claw_look|claw_scan|claw_look_sequence)\b", re.M)
SEND_BODY = re.compile(r"""\b(?:send|_tx|_write_pose)\(\s*["'](kup|kbalance|kcalib|krest|d)["']""")
FALL_NUM = re.compile(r"\b(fall_deg|fall_abort_deg)\s*[:=]\s*(?:float\s*=\s*)?([0-9]+(?:\.[0-9]+)?)")


def body_fall_deg() -> float:
    m = re.search(r"^FALL_DEG\s*=\s*([0-9.]+)", (PKG / "body.py").read_text(), re.M)
    return float(m.group(1)) if m else 60.0


def py_files():
    for f in sorted(PKG.rglob("*.py")):
        rel = f.relative_to(PKG).as_posix()
        if rel.startswith(("tests/", ".venv/")) or "/.venv/" in rel or "__pycache__" in rel:
            continue
        yield f, rel


def is_mode(rel: str) -> bool:
    return rel in MODE_FILES or rel.startswith(MODE_DIRS)


def exceptions_registered() -> str:
    try:
        return EXCEPTIONS.read_text()
    except OSError:
        return ""


def call_text(text: str, start: int) -> str:
    """The source of the call that opens at `start` (the matching parenthesis), for looking at its arguments."""
    depth, i = 0, text.index("(", start)
    for j in range(i, len(text)):
        depth += text[j] == "("
        depth -= text[j] == ")"
        if depth == 0:
            return text[start:j + 1]
    return text[start:start + 2000]


def violations() -> list[dict]:
    out = []
    fall = body_fall_deg()
    registered = exceptions_registered()
    for f, rel in py_files():
        text = f.read_text()
        lines = text.splitlines()

        def add(rule, n, why, blocking):
            out.append({"rule": rule, "file": rel, "line": n, "text": lines[n - 1].strip()[:90], "why": why, "blocking": blocking})
        for n, line in enumerate(lines, 1):
            if "MODE-SPECIFIC(" in line:
                if rel not in registered:
                    add("R7", n, "a MODE-SPECIFIC exception that docs/specification/mode-exceptions.md does not list", True)
                continue                                                          # a registered exception is allowed on this line
            if rel not in LOOK_HOME and LOOK_NAMES.match(line):
                add("R1", n, "a second claw look: every mode calls claw_survey.run_claw_look (the ball chase's sequence)", True)
            for m in FALL_NUM.finditer(line):
                if rel != "body.py" and float(m.group(2)) != fall:
                    add("R3", n, f"a fall threshold of {m.group(2)}: the body's is {fall:g} (pi_pipeline/body.py)", True)
            if is_mode(rel) and rel not in STANDARD_HOMES and SEND_BODY.search(line):
                add("R4", n, "a mode sends a stand / rest / attention command itself instead of calling the standard move", False)
        for m in re.finditer(r"\bStandGuard\(", text):
            n = text.count("\n", 0, m.start()) + 1
            if lines[n - 1].lstrip().startswith(("class ", "def ")) or rel == "gait/stand_guard.py":
                continue
            call = call_text(text, m.start())
            if rel not in GUARD_ENTRY:
                add("R2", n, "a StandGuard built outside the mode entry points (voice/__main__.py, explore_session.py)", True)
            elif "on_fall=" not in call:
                add("R2", n, "a StandGuard built without on_fall=", True)
            if "on_silent=" not in call:
                add("R5", n, "a StandGuard built without on_silent= (a deaf board must end every mode the same way)", False)
    return out


def key(v: dict) -> str:
    return f"{v['rule']}|{v['file']}|{v['text']}"


def load_baseline() -> set[str]:
    try:
        return set(json.loads(BASELINE.read_text()).get("known", []))
    except (OSError, ValueError):
        return set()


def check() -> tuple[list[dict], list[dict], list[dict]]:
    """(blocking violations, new ratchet violations, known ratchet violations)."""
    base = load_baseline()
    vs = violations()
    return [v for v in vs if v["blocking"]], [v for v in vs if not v["blocking"] and key(v) not in base], [v for v in vs if not v["blocking"] and key(v) in base]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--update-baseline" in argv:
        vs = [v for v in violations() if not v["blocking"]]
        BASELINE.write_text(json.dumps({"_help": "Known mode-consistency gaps (tools/check_modes.py). Fix one and run --update-baseline: the list only shrinks.", "known": sorted({key(v) for v in vs})}, indent=1) + "\n")
        print(f"baseline written: {len(vs)} known gap(s)")
        return 0
    blocking, new, known = check()
    for v in blocking:
        print(f"ERROR {v['rule']} {v['file']}:{v['line']}: {v['why']}\n      {v['text']}")
    for v in new:
        print(f"NEW   {v['rule']} {v['file']}:{v['line']}: {v['why']}\n      {v['text']}")
    if "--list" in argv:
        for v in known:
            print(f"known {v['rule']} {v['file']}:{v['line']}: {v['why']}\n      {v['text']}")
    print(f"check_modes: {len(blocking)} error(s), {len(new)} new gap(s), {len(known)} known gap(s) still to fix (python tools/check_modes.py --list)")
    return 1 if blocking or new else 0


if __name__ == "__main__":
    sys.exit(main())
