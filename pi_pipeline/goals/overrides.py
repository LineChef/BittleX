"""The user's overrides on what G2 learned (user, 2026-10-31: "a way to override learned settings in case a bad behavior is learned").

    ~/.local/share/g2/goal_overrides.json   (G2_GOAL_OVERRIDES moves it)   {goal: {scope: {"pins": {knob: value}, "limits": {knob: [lo, hi]}, "banned": {knob: {vkey: null}}}}}

A scope is "all" (every attachment and floor) or a conditions filter such as "floor=tile" or "attachment=arm|floor=hardwood": it applies to every conditions key that has all its
parts. Who wins: a pin (the user's value, G2 cannot change it) > a limit (G2 learns only inside the user's range) > what G2 learned > the user's own settings file. An undone value is
banned for good under its scope until the user clears it (`g2goal unban`). Every change is written to the goal journal (kind "override") and shown in the report.
"""
from __future__ import annotations

import json
import os

PATH = "~/.local/share/g2/goal_overrides.json"
KINDS = ("pins", "limits", "banned")


def path() -> str:
    return os.path.expanduser(os.environ.get("G2_GOAL_OVERRIDES", PATH))


def load(p: str | None = None) -> dict:
    try:
        return json.load(open(p or path()))
    except (OSError, ValueError):
        return {}


def save(data: dict, p: str | None = None) -> None:
    p = p or path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps(data, indent=1) + "\n")
    os.replace(tmp, p)


def scope_matches(scope: str, cond_key: str) -> bool:
    if scope == "all":
        return True
    parts = set(cond_key.split("|"))
    return all(s in parts for s in scope.split("|"))


def for_conditions(goal: str, cond_key: str, data: dict | None = None) -> dict:
    """The overrides that apply to one goal under one conditions key: "all" first, then each matching narrower scope on top."""
    data = load() if data is None else data
    out = {"pins": {}, "limits": {}, "banned": {}}
    scopes = data.get(goal) or {}
    for scope in sorted(scopes, key=lambda s: (s != "all", s.count("|"), s)):
        if not scope_matches(scope, cond_key):
            continue
        ov = scopes[scope]
        out["pins"].update(ov.get("pins") or {})
        out["limits"].update(ov.get("limits") or {})
        for knob, vals in (ov.get("banned") or {}).items():
            out["banned"].setdefault(knob, {}).update(vals)
    return out


def _entry(data: dict, goal: str, scope: str) -> dict:
    e = data.setdefault(goal, {}).setdefault(scope, {})
    for k in KINDS:
        e.setdefault(k, {})
    return e


def set_pin(goal: str, knob: str, value, scope: str = "all", p: str | None = None) -> None:
    data = load(p)
    _entry(data, goal, scope)["pins"][knob] = value
    save(data, p)


def clear(goal: str, kind: str, knob: str, scope: str = "all", p: str | None = None, value_key: str | None = None) -> bool:
    data = load(p)
    e = (data.get(goal) or {}).get(scope) or {}
    bucket = e.get(kind) or {}
    if knob not in bucket:
        return False
    if kind == "banned" and value_key is not None:
        hit = bucket[knob].pop(value_key, "missing") != "missing"
        if not bucket[knob]:
            bucket.pop(knob)
    else:
        bucket.pop(knob)
        hit = True
    save(data, p)
    return hit


def set_limit(goal: str, knob: str, lo: float, hi: float, scope: str = "all", p: str | None = None) -> None:
    if lo > hi:
        lo, hi = hi, lo
    data = load(p)
    _entry(data, goal, scope)["limits"][knob] = [lo, hi]
    save(data, p)


def ban(goal: str, knob: str, value_key: str, scope: str = "all", p: str | None = None) -> None:
    data = load(p)
    _entry(data, goal, scope)["banned"].setdefault(knob, {})[value_key] = None
    save(data, p)


def describe(goal: str, data: dict | None = None) -> list[str]:
    data = load() if data is None else data
    out = []
    for scope, e in sorted((data.get(goal) or {}).items()):
        for knob, v in (e.get("pins") or {}).items():
            out.append(f"pinned {knob} = {v} ({scope})")
        for knob, (lo, hi) in (e.get("limits") or {}).items():
            out.append(f"limited {knob} to {lo:g} to {hi:g} ({scope})")
        for knob, vals in (e.get("banned") or {}).items():
            out.append(f"undone {knob} = {', '.join(vals)} ({scope})")
    return out
