"""The settings for dialing in the punt, in one small file on the Pi that is read at the start of every punt run (user, 2026-10-26).

    ~/.local/share/g2/punt_settings.json        (G2_PUNT_SETTINGS moves it)

Edit a value, say "g2, punt" again, and the new value is used: no deploy and no code change. A missing file, a missing key or a bad value means the default in `behavior/ball_chase.py`
(a bad value is reported at the start of the run, never silently used). Distances are inches from the CAMERA to the ball (the jaws are about 1 in nearer).

    python -m pi_pipeline.behavior.punt_settings            # print the file's path and the values a run would use now
    python -m pi_pipeline.behavior.punt_settings --init     # write the file with every setting at its default (never overwrites an existing one)
    python -m pi_pipeline.behavior.punt_settings --set punt_max_in 3.5     # change one setting (checked first)
"""
from __future__ import annotations

import json
import os

# the search orders ball_chase knows (kept here as names so this module stays importable without numpy)
SEARCH_ORDER_NAMES = ("turn", "claw_then_turn", "claw_scan", "back_claw_scan", "claw_back_scan", "back_turn", "back_and_turn", "three_point_turn", "claw_three_point", "full_circle", "claw_full_circle", "turn_180", "claw_turn_180")

PATH = "~/.local/share/g2/punt_settings.json"

# name -> (ball_chase constant, kind, lowest, highest, what it does)
SPEC = {
    "punt_max_in": ("PUNT_MAX_IN", float, 1.0, 10.0, "punch when the ball is this close or closer (the main setting to dial in)"),
    "nudge_max_in": ("NUDGE_MAX_IN", float, 1.0, 12.0, "from punt_max_in out to this, take small steps closer first (set equal to punt_max_in for none)"),
    "nudges_before_punt": ("NUDGES_BEFORE_PUNT", int, 0, 10, "small steps closer before punching anyway from out of range"),
    "nudge_step_s": ("NUDGE_S", float, 0.3, 2.5, "length of one small step closer, seconds"),
    "nudge_gait": ("NUDGE_GAIT", str, ("scripted", "policy"), None, "how the small steps closer are walked: Petoi's scripted walk (steadier, the default) or the learned policy"),
    "walk_aim_in": ("WALK_AIM_IN", float, 1.5, 8.0, "the long walk steps are timed to leave the ball about this far from the camera"),
    "punt_align_deg": ("PUNT_ALIGN_DEG", float, 2.0, 30.0, "the ball must be within this many degrees of straight ahead before the punch"),
    "punch_lunge_s": ("PUNCH_LUNGE_S", float, 0.05, 0.6, "seconds for the lunge itself (smaller = harder and faster)"),
    "punch_hold_s": ("PUNCH_HOLD_S", float, 0.0, 1.0, "seconds the lunge is held before he comes back"),
    "lost_looks": ("LOST_LOOKS", int, 1, 8, "looks in a row without the ball before he starts searching"),
    "search_walk": ("SEARCH_WALK", bool, None, None, "after a full search circle, walk on blind (a big floor only; never on a desk)"),
    "max_seconds": (None, float, 10.0, 600.0, "an attempt ends (and he rests) after this many seconds"),
    # added with the goals plan (2026-10-31); a choice setting is (constant, str, the allowed values, None, what it does)
    "back_up_s": ("BACK_UP_S", float, 0.5, 4.0, "seconds of one back-up (after stuck punts, and as a search move)"),
    "stuck_punts": ("STUCK_PUNTS", int, 1, 6, "punts with the ball still in range before he backs up"),
    "back_up_budget_s": ("BACK_BUDGET_S", float, 0.0, 20.0, "the most backing up in one attempt (no edge detector: keep it small on a desk; 0 = never back up)"),
    "when_vanished": ("WHEN_VANISHED", str, ("punt", "back_up"), None, "the ball vanished at close range: punt (it is at the claw) or back up a little to see it"),
    "search_order": ("SEARCH_ORDER", str, tuple(SEARCH_ORDER_NAMES), None, "how he looks for the ball: claw looks, turn steps and back-ups in this order"),
    "search_step_deg": ("SEARCH_STEP_DEG", float, 10.0, 60.0, "one turn step of a search without claw looks, degrees"),
    "scan_turn_deg": ("SCAN_TURN_DEG", float, 20.0, 90.0, "one turn step between two claw looks, degrees"),
    "claw_look_pan_deg": ("CLAW_PAN_DEG", float, 10.0, 45.0, "how far to each side the claw look points the camera, degrees"),
    "claw_look_lift_deg": ("CLAW_LIFT_DEG", float, 0.0, 120.0, "how high the claw look lifts the arm (positive is up; 0 = level, 120 = near the top)"),
    "claw_pan_sign": ("CLAW_PAN_SIGN", str, ("right", "left"), None, "which way a positive arm pan turns the camera (measure it: python -m pi_pipeline.behavior.claw_look --calibrate)"),
    "align_pulse_min_s": ("ALIGN_PULSE_MIN_S", float, 0.3, 1.6, "the shortest small turn used to line the claw up with the ball, seconds"),
    "align_tries": ("ALIGN_TRIES", int, 1, 8, "small turns to line up before giving up (then when_misaligned)"),
    "when_misaligned": ("WHEN_MISALIGNED", str, ("punch", "back_up"), None, "still off line after align_tries small turns: punch anyway or back up and line up again"),
    "wall_sidestep_in": ("WALL_SIDESTEP_IN", float, 4.0, 14.0, "a ball against a wall: step this far sideways (toward the side with more room) and come at it from the side"),
    "wall_sidestep_deg": ("WALL_SIDESTEP_DEG", float, 10.0, 60.0, "a ball against a wall: how far to turn toward the side with more room before the sidestep"),
    "wall_sidestep_tries": ("WALL_SIDESTEP_TRIES", int, 0, 5, "sidesteps an attempt for a ball against a wall before he leaves it (0 = leave it)"),
    "between_moves": ("BETWEEN_MOVES", str, ("stand", "attention"), None, "while not moving: stand (default), or wait in the attention pose (legs straight) and stand up back legs first to move"),
}
DEFAULT_MAX_SECONDS = 75.0


def path() -> str:
    return os.path.expanduser(os.environ.get("G2_PUNT_SETTINGS", PATH))


def defaults(chase) -> dict:
    """Every setting at the value `ball_chase` has right now (`chase` is the module)."""
    out = {}
    for name, (const, kind, lo, hi, _doc) in SPEC.items():
        out[name] = DEFAULT_MAX_SECONDS if const is None else getattr(chase, const)
    return out


def load_file(p: str | None = None) -> tuple[dict, list]:
    """(valid settings from the file, problems). A missing file is no settings and no problem."""
    p = p or path()
    try:
        raw = json.load(open(p))
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError) as e:
        return {}, [f"{p} could not be read ({e}): the defaults are used"]
    good, problems = {}, []
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if k not in SPEC:
            problems.append(f"unknown setting {k!r} ignored (known: {', '.join(SPEC)})")
            continue
        _const, kind, lo, hi, _doc = SPEC[k]
        try:
            if kind is bool:
                if not isinstance(v, bool):
                    raise ValueError("must be true or false")
                val = v
            elif kind is str:
                if v not in lo:
                    raise ValueError(f"must be one of {', '.join(lo)}")
                val = v
            else:
                if isinstance(v, bool):
                    raise ValueError("must be a number")
                val = kind(v)
                if val < lo or val > hi:
                    raise ValueError(f"must be between {lo} and {hi}")
        except (TypeError, ValueError) as e:
            problems.append(f"{k} = {v!r} ignored: {e}")
            continue
        good[k] = val
    return good, problems


def apply(chase, settings: dict) -> None:
    """Put the settings into `ball_chase`'s constants (max_seconds is returned by `effective`, not a constant)."""
    for k, v in settings.items():
        const = SPEC[k][0]
        if const is not None:
            setattr(chase, const, v)


def effective(chase, p: str | None = None) -> tuple[dict, list]:
    """Apply the file to `chase` and return (every setting as it now is, problems)."""
    base = defaults(chase)
    got, problems = load_file(p)
    apply(chase, got)
    base.update(got)
    return base, problems


def set_value(chase, name: str, text: str, p: str | None = None) -> str:
    """Write `name` = `text` into the settings file (created from the defaults when missing) after checking it like a load would. Returns what happened; raises ValueError for a bad name or value."""
    p = p or path()
    if name not in SPEC:
        raise ValueError(f"unknown setting {name!r}; the settings are: {', '.join(SPEC)}")
    kind, lo, hi = SPEC[name][1], SPEC[name][2], SPEC[name][3]
    if kind is bool:
        if text.strip().lower() not in ("true", "false", "yes", "no", "on", "off", "1", "0"):
            raise ValueError(f"{name} must be true or false")
        val = text.strip().lower() in ("true", "yes", "on", "1")
    elif kind is str:
        val = text.strip()
        if val not in lo:
            raise ValueError(f"{name} must be one of {', '.join(lo)}")
    else:
        try:
            val = kind(float(text)) if kind is int else float(text)
        except ValueError:
            raise ValueError(f"{name} must be a number") from None
        if val < lo or val > hi:
            raise ValueError(f"{name} must be between {lo} and {hi}")
    try:
        data = json.load(open(p))
    except FileNotFoundError:
        data = json.loads(template(chase))
    except (OSError, ValueError) as e:
        raise ValueError(f"{p} could not be read ({e}); fix or delete it first") from None
    old = data.get(name)
    data[name] = val
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(json.dumps(data, indent=2) + "\n")
    return f"{name}: {old} -> {val}"


def template(chase) -> str:
    d = defaults(chase)
    body = {"_help": "Edit a value and say 'g2, punt' again: it is read at the start of every run. Distances are inches from the camera to the ball. See docs/guides/punt.md."}
    body.update({k: d[k] for k in SPEC})
    return json.dumps(body, indent=2) + "\n"


def main() -> None:
    import argparse

    from . import ball_chase as chase
    ap = argparse.ArgumentParser(description="Show or create the punt settings file.")
    ap.add_argument("--init", action="store_true", help="write the file with every setting at its default (never overwrites)")
    ap.add_argument("--set", nargs=2, metavar=("NAME", "VALUE"), help="change one setting, e.g. --set punt_max_in 3.5")
    args = ap.parse_args()
    p = path()
    if args.set:
        try:
            print("set", set_value(chase, args.set[0], args.set[1]))
        except ValueError as e:
            print("NOT CHANGED:", e)
            raise SystemExit(2)
    if args.init:
        if os.path.exists(p):
            print(f"{p} already exists: left alone")
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(template(chase))
            print(f"wrote {p}")
    eff, problems = effective(chase)
    print(f"settings file: {p} ({'present' if os.path.exists(p) else 'not there: all defaults'})")
    for k, v in eff.items():
        print(f"  {k:20s} {v!s:8s} {SPEC[k][4]}")
    for pr in problems:
        print("  PROBLEM:", pr)


if __name__ == "__main__":
    main()
