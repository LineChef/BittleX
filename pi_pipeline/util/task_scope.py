"""A task leaves nothing behind (user, 2026-11-01): the settings a task changes are put back when it ends, whatever way it ends.

The chase, the walls goal and the goal sessions write their settings into module constants (`ball_chase.PUNT_MAX_IN`, `wall_distance.TURN_IN`, ...). In a service that never restarts a value one
task set stayed set for the next (the wall settings did once). Every task (a goal session, an exploration, a chase) now runs inside

    with task_scope("goal session ball_punt") as scope:
        ...
        scope.on_exit(fn)          # anything else to undo (lent hardware, a stop file); runs at the end, newest first, never raises

On the way in it compares every setting with the process's baseline (read the first time any task started): a difference means something changed a setting OUTSIDE a task, and is logged
(`task.leak_at_start`, and a note in the memory log). On the way out it puts back every setting that changed, in a `finally`, so a stop, an error or a fall cannot skip it. A change to
a constant that is not a declared setting (the settings tables of `behavior/punt_settings.py` and `behavior/wall_settings.py`) is restored too and logged (`task.undeclared_change`); with
`G2_TASK_SCOPE_STRICT=1` (the tests) it raises. The settings are the UPPER_CASE numbers, strings and truths of the chase module, the wall distance module, the exploration module and the behavior driver.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sys
import time

log = logging.getLogger(__name__)
_BASELINE: dict | None = None
_SIMPLE = (int, float, str, bool, type(None))


def _targets() -> dict:
    """name -> the module or class holding settings. The chase module is the running one (it may be `__main__`), and the imported one when that differs."""
    from ..behavior import ball_chase, driver
    from .. import explore_session
    from ..vision import wall_distance
    out = {"chase": sys.modules.get(ball_chase.__name__, ball_chase), "walldist": wall_distance, "explore": explore_session, "driver": driver.BehaviorDriver}
    if sys.modules.get("__main__") is not None and getattr(sys.modules["__main__"], "__file__", "").endswith("ball_chase.py"):
        out["chase_main"] = sys.modules["__main__"]
    return out


def _declared() -> set:
    from ..behavior import punt_settings, wall_settings
    d = {("chase", c) for (c, *_r) in punt_settings.SPEC.values() if c}
    d |= {("chase_main", c) for (c, *_r) in punt_settings.SPEC.values() if c}
    d |= {(where, const) for (where, const, *_r) in wall_settings.SPEC.values()}
    return d


def capture(targets: dict | None = None) -> dict:
    """{(target, NAME): value} for every simple UPPER_CASE constant of the targets."""
    out = {}
    for tname, obj in (targets if targets is not None else _targets()).items():
        for name in dir(obj):
            if name.isupper() and not name.startswith("_"):
                try:
                    v = getattr(obj, name)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(v, _SIMPLE):
                    out[(tname, name)] = v
    return out


def _diff(before: dict, now: dict) -> dict:
    return {k: (before[k], now[k]) for k in before if k in now and before[k] != now[k]}


def _put_back(values: dict, targets: dict, keys) -> None:
    for tname, name in keys:
        try:
            setattr(targets[tname], name, values[(tname, name)])
        except Exception:  # noqa: BLE001
            pass


def _event(name: str, **kv) -> None:
    try:
        from ..diag import diag
        diag.event("task", "WARN", name, **kv)
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..diag import memlog
        memlog.note(name, **{k: str(v)[:200] for k, v in kv.items()})
    except Exception:  # noqa: BLE001
        pass
    log.warning("%s %s", name, kv)


def strict() -> bool:
    return os.environ.get("G2_TASK_SCOPE_STRICT", "") == "1"


class Scope:
    def __init__(self, name: str):
        self.name = name
        self.leaks: list[str] = []                 # what was found changed outside a task, or changed without being declared
        self._exits: list = []

    def on_exit(self, fn) -> None:
        self._exits.append(fn)


@contextlib.contextmanager
def task_scope(name: str, targets: dict | None = None, declared: set | None = None):
    """See the module docstring. `targets`/`declared` are for tests."""
    global _BASELINE
    default_targets = targets is None
    targets = targets if targets is not None else _targets()
    declared = declared if declared is not None else _declared()
    scope = Scope(name)
    start = capture(targets)
    if default_targets and _BASELINE is None:
        _BASELINE = dict(start)                                               # what this process had before any task changed anything
    base = _BASELINE if default_targets else start
    stray = {k: v for k, v in _diff(base, start).items()}
    if stray:
        scope.leaks += [f"{k[0]}.{k[1]} was {a!r} at start, now {b!r}" for k, (a, b) in stray.items()]
        _event("task.leak_at_start", task=name, changed=scope.leaks[:8])
        _put_back(base, targets, stray.keys())                                # a task starts from the baseline, whatever was left
        start = capture(targets)
    try:
        from ..diag import memlog
        memlog.note(f"{name} start")
    except Exception:  # noqa: BLE001
        pass
    try:
        yield scope
    finally:
        for fn in reversed(scope._exits):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        now = capture(targets)
        changed = _diff(start, now)
        undeclared = [k for k in changed if k not in declared]
        _put_back(start, targets, changed.keys())
        if undeclared:
            msgs = [f"{k[0]}.{k[1]}: {changed[k][0]!r} -> {changed[k][1]!r}" for k in undeclared]
            scope.leaks += msgs
            _event("task.undeclared_change", task=name, changed=msgs[:8])
        try:
            from ..diag import memlog
            memlog.note(f"{name} end", settings_restored=len(changed), undeclared=len(undeclared))
        except Exception:  # noqa: BLE001
            pass
        if undeclared and strict():
            raise AssertionError(f"task {name!r} changed settings it did not declare: {', '.join(scope.leaks)}")
