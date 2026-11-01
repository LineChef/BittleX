"""The settings for turning away from walls, in one small file on the Pi (goals plan, the "turn away from walls" standing goal, 2026-10-31).

    ~/.local/share/g2/wall_settings.json        (G2_WALL_SETTINGS moves it)

They are the wall constants the exploration reflex (`behavior/driver.py`, `explore_session.py`) and the ball chase (`behavior/ball_chase.py`) already use; a missing file or value
means the code's default. The walls goal (`goals/walls.py`) starts from these and changes the free ones itself as he learns; this file changes only when you edit it.

    python -m pi_pipeline.behavior.wall_settings                    # the values a run would use now
    python -m pi_pipeline.behavior.wall_settings --set wall_stop_in 14
"""
from __future__ import annotations

import json
import math
import os

PATH = "~/.local/share/g2/wall_settings.json"

# name -> (where, constant, kind, lowest, highest, what it does). where: "driver" (BehaviorDriver class), "explore" (explore_session module), "chase" (ball_chase module).
SPEC = {
    "wall_stop_in": ("driver", "WALL_STOP_IN", float, 6.0, 30.0, "exploring: a wall this close is acted on from a single look, inches"),
    "wall_turn_deg": ("driver", "WALL_TURN_RAD", float, 30.0, 120.0, "how far he turns away from a near wall, degrees (also in the ball chase)"),
    "leg_margin_in": ("driver", "LEG_MARGIN_IN", float, 6.0, 30.0, "exploring: the next walk is cut short so he stops this far from the nearest wall, inches"),
    "near_look_in": ("explore", "NEAR_LOOK_IN", float, 12.0, 48.0, "exploring: a wall this close starts the fast looks, inches"),
    "chase_wall_in": ("chase", "CHASE_WALL_IN", float, 6.0, 24.0, "chasing the ball: never closer than this to a wall; a ball nearer the wall than this is left alone, inches"),
}
RADIANS = {"wall_turn_deg"}              # kept in degrees here, radians in the code


def path() -> str:
    return os.path.expanduser(os.environ.get("G2_WALL_SETTINGS", PATH))


def _targets():
    from . import ball_chase, driver
    from .. import explore_session
    return {"driver": driver.BehaviorDriver, "explore": explore_session, "chase": ball_chase}


def defaults(targets=None) -> dict:
    t = targets or _targets()
    out = {}
    for name, (where, const, _kind, _lo, _hi, _doc) in SPEC.items():
        v = getattr(t[where], const)
        out[name] = round(math.degrees(v), 1) if name in RADIANS else float(v)
    return out


def load_file(p: str | None = None) -> tuple[dict, list]:
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
            problems.append(f"unknown setting {k!r} ignored")
            continue
        lo, hi = SPEC[k][3], SPEC[k][4]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= float(v) <= hi:
            problems.append(f"{k} = {v!r} ignored: must be between {lo} and {hi}")
            continue
        good[k] = float(v)
    return good, problems


def apply(values: dict, targets=None) -> None:
    """Put the values into the code's constants."""
    t = targets or _targets()
    for name, v in values.items():
        if name not in SPEC:
            continue
        where, const = SPEC[name][0], SPEC[name][1]
        setattr(t[where], const, math.radians(float(v)) if name in RADIANS else float(v))


def effective(targets=None, p: str | None = None) -> tuple[dict, list]:
    """The user's file applied over the defaults (the constants are set too): (every setting as it now is, problems)."""
    base = defaults(targets)
    got, problems = load_file(p)
    base.update(got)
    apply(got, targets)
    return base, problems


def set_value(name: str, text: str, p: str | None = None) -> str:
    p = p or path()
    if name not in SPEC:
        raise ValueError(f"unknown setting {name!r}; the settings are: {', '.join(SPEC)}")
    lo, hi = SPEC[name][3], SPEC[name][4]
    try:
        v = float(text)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    try:
        data = json.load(open(p))
    except FileNotFoundError:
        data = {}
    old = data.get(name)
    data[name] = v
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    open(p, "w").write(json.dumps(data, indent=2) + "\n")
    return f"{name}: {old} -> {v}"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Show or change the wall settings.")
    ap.add_argument("--set", nargs=2, metavar=("NAME", "VALUE"))
    a = ap.parse_args()
    if a.set:
        try:
            print("set", set_value(*a.set))
        except ValueError as e:
            raise SystemExit(f"NOT CHANGED: {e}")
    eff, problems = effective()
    print(f"settings file: {path()} ({'present' if os.path.exists(path()) else 'not there: all defaults'})")
    for k, v in eff.items():
        print(f"  {k:16s} {v!s:8s} {SPEC[k][5]}")
    for pr in problems:
        print("  PROBLEM:", pr)


if __name__ == "__main__":
    main()
