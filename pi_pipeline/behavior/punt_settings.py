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

PATH = "~/.local/share/g2/punt_settings.json"

# name -> (ball_chase constant, kind, lowest, highest, what it does)
SPEC = {
    "punt_max_in": ("PUNT_MAX_IN", float, 1.0, 10.0, "punch when the ball is this close or closer (the main setting to dial in)"),
    "nudge_max_in": ("NUDGE_MAX_IN", float, 1.0, 12.0, "from punt_max_in out to this, take small steps closer first (set equal to punt_max_in for none)"),
    "nudges_before_punt": ("NUDGES_BEFORE_PUNT", int, 0, 10, "small steps closer before punching anyway from out of range"),
    "nudge_step_s": ("NUDGE_S", float, 0.3, 2.5, "length of one small step closer, seconds"),
    "walk_aim_in": ("WALK_AIM_IN", float, 1.5, 8.0, "the long walk steps are timed to leave the ball about this far from the camera"),
    "punt_align_deg": ("PUNT_ALIGN_DEG", float, 2.0, 30.0, "the ball must be within this many degrees of straight ahead before the punch"),
    "punch_lunge_s": ("PUNCH_LUNGE_S", float, 0.05, 0.6, "seconds for the lunge itself (smaller = harder and faster)"),
    "punch_hold_s": ("PUNCH_HOLD_S", float, 0.0, 1.0, "seconds the lunge is held before he comes back"),
    "lost_looks": ("LOST_LOOKS", int, 1, 8, "looks in a row without the ball before he starts searching"),
    "search_walk": ("SEARCH_WALK", bool, None, None, "after a full search circle, walk on blind (a big floor only; never on a desk)"),
    "max_seconds": (None, float, 10.0, 600.0, "an attempt ends (and he rests) after this many seconds"),
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
