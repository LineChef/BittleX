"""`python -m pi_pipeline.goals` (alias g2goal): goals the user sets, sessions, what G2 learned, the report.

    python -m pi_pipeline.goals list                                   # the goals and their start phrases
    python -m pi_pipeline.goals show ball_punt                         # its settings: who changes each (free / ask / fixed), bounds, what G2 has now
    python -m pi_pipeline.goals set ball_punt --attempts 10 --control punch_lunge_s=fixed     # the user changes a goal (only the user sets goals)
    python -m pi_pipeline.goals run ball_punt                          # one session on the Pi (voice service stopped; "G2, ball goal" does this through goal_launch)
    python -m pi_pipeline.goals stop                                   # end a running session after the current move (he rests)
    python -m pi_pipeline.goals status                                 # what each goal has learned, per attachment and floor
    python -m pi_pipeline.goals history ball_punt                      # the last sessions as text
    python -m pi_pipeline.goals report ball_punt --html out.html       # the report page
    python -m pi_pipeline.goals reset ball_punt --yes                  # forget what a goal learned (the journal keeps the history)
    python -m pi_pipeline.goals suggestions                            # suggestions for the settings only you change (G2 also says new ones when the voice service starts)
    python -m pi_pipeline.goals confirm ball_punt punch_lunge_s        # ... or cancel
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import replace

from . import spec
from .journal import Journal, State

STOP_FILE = "~/.local/share/g2/goal_stop"


def stop_path() -> str:
    return os.path.expanduser(STOP_FILE)


def _stop_requested() -> bool:
    from ..behavior.ball_chase import STOP_FILE as CHASE_STOP
    return os.path.exists(stop_path()) or os.path.exists(os.path.expanduser(CHASE_STOP))


def _goal(goals, gid):
    if gid not in goals:
        raise SystemExit(f"no goal {gid!r} (known: {', '.join(goals)})")
    return goals[gid]


def cmd_show(goal) -> None:
    from .approach import make
    from .judge import Judge
    from .journal import conditions_key, current_conditions
    ap = make(goal.approach)
    knobs = goal.knobs(ap.knobs())
    base = ap.base_settings()
    cond = conditions_key(current_conditions(ap.conditions()))
    st = State().data.get(goal.id, {}).get(cond)
    now = Judge(knobs, ap.diagnosis, dict(st) if st else None).settings(base)
    print(f"{goal.title} ({goal.id}): approach {goal.approach}, {goal.attempts} attempts a session, {goal.minutes:g} min max, pack at least {goal.min_pack_pct}%"
          + (f", ends after {goal.target_successes} successes" if goal.target_successes else ""))
    print(f"start phrases: {', '.join(goal.start_words) or '(none)'}; conditions now: {cond}; learned from {st.get('count', 0) if st else 0} attempts here")
    for k in knobs:
        rng = f"{k.lo:g} to {k.hi:g}, step {k.step:g}" if k.kind in ("float", "int") and k.step else (", ".join(map(str, k.options)) if k.options else k.kind)
        yours = "" if now.get(k.name) == base.get(k.name) else f"  (yours: {base.get(k.name)})"
        print(f"  {k.control:5s}  {k.name:20s} {str(now.get(k.name)):12s} {rng}{yours}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="g2goal", description="Goals G2 works toward, and what he learns from his attempts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("show"); p.add_argument("goal")
    p = sub.add_parser("set", help="change a goal or add one (only the user sets goals)")
    p.add_argument("goal")
    p.add_argument("--approach", help="for a new goal: which approach (known: ball_punt)")
    p.add_argument("--title")
    p.add_argument("--attempts", type=int)
    p.add_argument("--minutes", type=float)
    p.add_argument("--min-pack", type=int, dest="min_pack_pct")
    p.add_argument("--target", type=int, dest="target_successes", help="end a session after this many successes (0 = use every attempt)")
    p.add_argument("--rest", type=float, dest="rest_between_s", help="seconds standing still between attempts")
    p.add_argument("--control", action="append", default=[], metavar="KNOB=free|ask|fixed")
    p.add_argument("--start-words", nargs="+", help="spoken start phrases")
    p = sub.add_parser("run"); p.add_argument("goal"); p.add_argument("--quiet", action="store_true", help="no spoken cues")
    sub.add_parser("stop")
    sub.add_parser("status")
    p = sub.add_parser("history"); p.add_argument("goal"); p.add_argument("--last", type=int, default=3)
    p = sub.add_parser("report"); p.add_argument("goal", nargs="?", default="ball_punt"); p.add_argument("--html", required=True)
    p = sub.add_parser("reset"); p.add_argument("goal"); p.add_argument("--yes", action="store_true")
    sub.add_parser("suggestions", help="the suggestions for settings only you change, with their status")
    for name in ("confirm", "cancel"):
        p = sub.add_parser(name, help=f"{name} a suggestion"); p.add_argument("goal"); p.add_argument("knob")
    a = ap.parse_args(argv)
    goals, problems = spec.load()
    for pr in problems:
        print("GOALS FILE PROBLEM:", pr)

    if a.cmd == "list":
        for g in goals.values():
            print(f"{g.id:12s} {g.title} ({g.approach}, {g.attempts} attempts): say {', '.join(repr('G2, ' + w) for w in g.start_words[:2]) or '(no phrase)'}")
    elif a.cmd == "show":
        cmd_show(_goal(goals, a.goal))
    elif a.cmd == "set":
        if a.goal in goals:
            g = goals[a.goal]
        else:
            if not a.approach:
                raise SystemExit("a new goal needs --approach")
            g = spec.Goal(a.goal, a.title or a.goal, a.approach)
        changes = {k: getattr(a, k) for k in ("title", "attempts", "minutes", "min_pack_pct", "target_successes", "rest_between_s") if getattr(a, k) is not None}
        if changes.get("target_successes") == 0:
            changes["target_successes"] = None
        if a.approach:
            changes["approach"] = a.approach
        if a.start_words:
            changes["start_words"] = tuple(w.lower() for w in a.start_words)
        controls = dict(g.controls)
        from .approach import make
        names = {k.name for k in make(changes.get("approach", g.approach)).knobs()}
        for c in a.control:
            name, _, val = c.partition("=")
            if name not in names or val not in spec.CONTROLS:
                raise SystemExit(f"bad --control {c!r}: KNOB=free|ask|fixed, KNOB one of {', '.join(sorted(names))}")
            controls[name] = val
        g = replace(g, controls=controls, **changes)
        spec.save_goal(g)
        print(f"saved {g.id} in {spec.path()}")
        cmd_show(g)
    elif a.cmd == "run":
        logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
        g = _goal(goals, a.goal)
        from .approach import make
        from .runner import GoalSession
        announce = None
        if not a.quiet:
            try:
                from ..config import settings
                from ..voice.tts import make_tts
                _tts = make_tts("piper", piper_model_path=settings.piper_model_path, style=settings.voice_style)
                announce = lambda text: text and _tts.speak(text)        # noqa: E731
            except Exception as e:  # noqa: BLE001
                print("no voice (", e, "): the cues are printed only")
        from ..behavior.ball_chase import STOP_FILE as CHASE_STOP
        for f in (stop_path(), os.path.expanduser(CHASE_STOP)):
            try:
                os.remove(f)
            except FileNotFoundError:
                pass
        try:
            GoalSession(g, make(g.approach), stop=_stop_requested, announce=announce).run()
        except KeyboardInterrupt:
            print("ended: stopped")
    elif a.cmd == "stop":
        os.makedirs(os.path.dirname(stop_path()), exist_ok=True)
        open(stop_path(), "w").close()
        print("stop requested: the session ends after the current move")
    elif a.cmd == "status":
        data = State().data
        if not data:
            print("nothing learned yet")
        for gid, per in data.items():
            for cond, st in per.items():
                tr = st.get("trial")
                print(f"{gid} [{cond}]: {st.get('count', 0)} attempts; changed from yours: {st.get('settings') or 'nothing'}"
                      + (f"; trying {tr['knob']} {tr['old']} -> {tr['new']}" if tr else "") + (f"; suggestions: {st['suggestions']}" if st.get("suggestions") else ""))
    elif a.cmd == "history":
        from .report import text_history
        print(text_history(a.goal, last=a.last))
    elif a.cmd == "report":
        from .report import goal_page
        path = os.path.expanduser(a.html)
        open(path, "w").write(goal_page(a.goal))
        print("wrote", path)
    elif a.cmd == "suggestions":
        from .suggestions import describe, pending
        items = pending(State(), statuses=("new", "later"))
        if not items:
            print("no suggestions")
        for gid, cond, knob, e in items:
            print(f"[{e.get('status', 'new')}] {gid} {knob} ({cond}): {describe(gid, knob, e)}")
    elif a.cmd in ("confirm", "cancel"):
        from .suggestions import pending, resolve
        st = State()
        hits = [(g, c, k) for g, c, k, _e in pending(st, statuses=("new", "later")) if g == a.goal and k == a.knob]
        if not hits:
            raise SystemExit(f"no suggestion for {a.goal} {a.knob}")
        for g, c, k in hits:
            print(resolve(g, c, k, a.cmd, state=st))
    elif a.cmd == "reset":
        if not a.yes:
            raise SystemExit("this forgets what the goal learned (the journal is kept): add --yes")
        print("forgotten" if State().reset(a.goal) else "nothing was learned for it")


if __name__ == "__main__":
    main(sys.argv[1:])
