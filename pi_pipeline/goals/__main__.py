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

Overrides, when G2 learned something bad (goals/overrides.py; add --floor tile or --scope attachment=arm|floor=tile to narrow them, default: everywhere):

    python -m pi_pipeline.goals pin ball_punt punt_max_in 3.5          # hold a setting at your value; G2 cannot change it (unpin to give it back)
    python -m pi_pipeline.goals limit ball_punt punt_max_in 2.5 4.5    # G2 keeps learning it, only inside your range (unlimit to clear)
    python -m pi_pipeline.goals undo ball_punt punt_max_in             # take back what he learned for it: his best value is banned, he goes to his next best (unban to clear)
    python -m pi_pipeline.goals forget ball_punt punt_max_in           # drop his record for one setting: back to your file's value, he may learn it again
    python -m pi_pipeline.goals overrides ball_punt                    # list them

Your verdict on how an attempt was scored (the number is the one in the report):

    python -m pi_pipeline.goals verdict ball_punt 7 wrong              # scored wrong: taken out of his records (right: kept, and counted as agreement)

Several goals:

    python -m pi_pipeline.goals priority                               # the order, highest first (walls above the punt by default)
    python -m pi_pipeline.goals priority walls ball_punt               # set it
    python -m pi_pipeline.goals practise [walls]                       # what "G2, practise" would choose now, with each goal's score
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


def _judge_for(goal, cond: str | None = None, state: State | None = None):
    """(approach, knobs, base settings, conditions key, judge over a COPY of the stored state, overrides)."""
    import copy

    from . import overrides as ovr
    from .approach import make
    from .judge import Judge
    from .journal import conditions_key, current_conditions
    ap = make(goal.approach)
    knobs = goal.knobs(ap.knobs())
    base = ap.base_settings()
    cond = cond or conditions_key(current_conditions(ap.conditions()))
    st = (state or State()).data.get(goal.id, {}).get(cond)
    ov = ovr.for_conditions(goal.id, cond)
    j = Judge(knobs, ap.diagnosis, copy.deepcopy(st) if st else None, stage_of=getattr(ap, "stage_of", None), overrides=ov)
    return ap, knobs, base, cond, j, ov


def _scope(a) -> str:
    if getattr(a, "scope", None):
        return a.scope
    if getattr(a, "floor", None):
        return f"floor={a.floor}"
    return "all"


def _value_for(knob, text: str):
    """A value the user typed, checked against the setting's own range; a bad one stops with a message (nothing is changed)."""
    try:
        if knob.kind == "choice":
            return knob.check(text)
        if knob.kind == "bool":
            return knob.check(text.strip().lower() in ("true", "yes", "on", "1"))
        return knob.check(int(float(text)) if knob.kind == "int" else float(text))
    except ValueError as e:
        raise SystemExit(f"not changed: {e}") from None


def cmd_show(goal) -> None:
    ap, knobs, base, cond, j, ov = _judge_for(goal)
    st = j.state if j.state.get("count") else None
    j.begin_session(base)
    now = j.settings(base)
    print(f"{goal.title} ({goal.id}): approach {goal.approach}, {goal.attempts} attempts a session, {goal.minutes:g} min max, pack at least {goal.min_pack_pct}%"
          + (f", ends after {goal.target_successes} successes" if goal.target_successes else ""))
    print(f"start phrases: {', '.join(goal.start_words) or '(none)'}; conditions now: {cond}; learned from {st.get('count', 0) if st else 0} attempts here")
    print(f"working on: {j.state.get('focus') or 'nothing yet'}")
    for k in knobs:
        rng = f"{k.lo:g} to {k.hi:g}, step {k.step:g}" if k.kind in ("float", "int") and k.step else (", ".join(map(str, k.options)) if k.options else k.kind)
        yours = "" if now.get(k.name) == base.get(k.name) else f"  (yours: {base.get(k.name)})"
        pin = "  PINNED by you" if k.name in ov["pins"] else ""
        lim = f"  limited by you to {ov['limits'][k.name][0]:g}-{ov['limits'][k.name][1]:g}" if k.name in ov["limits"] else ""
        recs = j.state["values"].get(k.name) or {}
        rec = "  record: " + ", ".join(f"{k.show(r['v'])} {r['hits']}/{r['n']}" for r in sorted(recs.values(), key=lambda r: str(r["v"])) if r["n"]) if any(r["n"] for r in recs.values()) else ""
        print(f"  {k.control:5s}  {k.name:20s} {str(now.get(k.name)):12s} {rng}{yours}{pin}{lim}{rec}")



def _run_standalone(g, a) -> None:
    """The session in this process (the old way): the voice service is stopped first and started again at the end, with G2 laid down in the rest pose before that.
    When the service is not running (the systemd hand-over unit stopped it itself) nothing is stopped or started."""
    import subprocess
    import time
    from . import inprocess
    was_active = inprocess.service_active()
    if was_active:
        subprocess.run(["sudo", "-n", "systemctl", "stop", "g2-voice"], timeout=60)
    try:
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
    finally:
        if was_active:
            try:
                subprocess.run([sys.executable, "-m", "pi_pipeline.link.check_serial", "send", "krest"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)
            subprocess.run(["sudo", "-n", "systemctl", "--no-block", "start", "g2-voice"], timeout=60)

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
    p = sub.add_parser("run", help="run a goal session: inside the running voice service (default), or on its own with --standalone")
    p.add_argument("goal"); p.add_argument("--quiet", action="store_true", help="no spoken cues")
    p.add_argument("--standalone", action="store_true", help="do not ask the voice service: stop it, run the session in this process, start it again (the old way; also G2_GOAL_INPROCESS=0)")
    sub.add_parser("stop")
    sub.add_parser("status")
    p = sub.add_parser("history"); p.add_argument("goal"); p.add_argument("--last", type=int, default=3)
    p = sub.add_parser("report"); p.add_argument("goal", nargs="?", default="ball_punt"); p.add_argument("--html", required=True)
    p = sub.add_parser("reset"); p.add_argument("goal"); p.add_argument("--yes", action="store_true")
    for name, extra in (("pin", ("value",)), ("unpin", ()), ("limit", ("lo", "hi")), ("unlimit", ()), ("undo", ()), ("unban", ("value",)), ("forget", ())):
        p = sub.add_parser(name)
        p.add_argument("goal"); p.add_argument("knob")
        for x in extra:
            p.add_argument(x)
        p.add_argument("--floor", help="only on this floor label")
        p.add_argument("--scope", help="a conditions filter, e.g. attachment=arm|floor=tile (default: everywhere)")
    p = sub.add_parser("overrides"); p.add_argument("goal")
    p = sub.add_parser("priority", help="show or set the goals' order, highest first (a standing goal above a task limits it)"); p.add_argument("order", nargs="*")
    p = sub.add_parser("practise", help="what 'G2, practise' would choose now, and why"); p.add_argument("words", nargs="*")
    p = sub.add_parser("curate", help="retire old-scoring attempts, check the saved lessons against their evidence, rotate logs, empty the trash (also runs after every session and pull)")
    p.add_argument("--dry", action="store_true", help="say what it would do and change nothing"); p.add_argument("--restore", action="store_true", help="put the deleted lessons back")
    p.add_argument("--mac-history", metavar="DIR", help="only prune DIR/history (the Mac copy of the goal data)")
    p = sub.add_parser("verdict", help="say whether an attempt was scored right; a wrong one is taken out of his records")
    p.add_argument("goal"); p.add_argument("number", type=int); p.add_argument("verdict", choices=("right", "wrong"))
    p.add_argument("--floor"); p.add_argument("--scope"); p.add_argument("--note", default="")
    p = sub.add_parser("lesson", help="add, edit or delete a lesson G2 saved to memory (a delete goes to the review Trash, so it can be put back)")
    p.add_argument("action", choices=("add", "edit", "delete")); p.add_argument("args", nargs="*", help="add TEXT | edit ID TEXT | delete ID")
    sub.add_parser("suggestions", help="the suggestions for settings only you change, with their status")
    for name in ("confirm", "cancel"):
        p = sub.add_parser(name, help=f"{name} a suggestion"); p.add_argument("goal"); p.add_argument("knob")
    a = ap.parse_args(argv)
    goals, problems = spec.load()
    for pr in problems:
        print("GOALS FILE PROBLEM:", pr)

    if a.cmd == "list":
        for g in goals.values():
            if g.kind == "standing":
                print(f"{g.id:12s} {g.title} (standing: always on, learns from every activity; 'G2, practise {g.practice_words[0] if g.practice_words else g.id}' = a {g.minutes:g}-minute roam)")
            else:
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
        from . import inprocess
        if not a.standalone:
            res = inprocess.delegate(g.id)                           # inside the running voice service: its serial port stays open (docs/STATUS.md open problems 15 and 18)
            if res is not None:
                print("session ended:", res.get("why"))
                return
        _run_standalone(g, a)
    elif a.cmd == "stop":
        os.makedirs(os.path.dirname(stop_path()), exist_ok=True)
        open(stop_path(), "w").close()
        print("stop requested: the session ends after the current move")
    elif a.cmd == "status":
        data = State().data
        if not data:
            print("nothing learned yet")
        for gid, per in data.items():
            g = goals.get(gid)
            for cond, st in per.items():
                line = f"{gid} [{cond}]: {st.get('count', 0)} attempts; working on {st.get('focus') or 'nothing'}"
                if g is not None:
                    _ap, _k, base, _c, j, _ov = _judge_for(g, cond)
                    best = {n: j.best(n, base[n]) for n, kk in j.knobs.items() if kk.control == "free" and n in base}
                    diff = {n: v for n, v in best.items() if v != base.get(n)}
                    line += f"; his best values that differ from yours: {diff or 'none'}"
                if st.get("suggestions"):
                    line += f"; suggestions: {', '.join(st['suggestions'])}"
                print(line)
    elif a.cmd in ("pin", "unpin", "limit", "unlimit", "undo", "unban", "forget"):
        from . import overrides as ovr
        g = _goal(goals, a.goal)
        ap_, knobs, base, cond, j, _ov = _judge_for(g)
        k = next((x for x in knobs if x.name == a.knob), None)
        if k is None:
            raise SystemExit(f"no setting {a.knob!r} (known: {', '.join(x.name for x in knobs)})")
        scope = _scope(a)
        journal = Journal()
        if a.cmd == "pin":
            v = _value_for(k, a.value)
            ovr.set_pin(g.id, k.name, v, scope)
            msg = f"pinned {k.name} = {v} ({scope}): G2 will not change it"
        elif a.cmd == "unpin":
            msg = f"unpinned {k.name} ({scope})" if ovr.clear(g.id, "pins", k.name, scope) else f"{k.name} was not pinned under {scope}"
        elif a.cmd == "limit":
            if k.kind not in ("float", "int"):
                raise SystemExit(f"not changed: {k.name} is a {k.kind} setting; pin it instead")
            lo, hi = _value_for(k, a.lo), _value_for(k, a.hi)
            ovr.set_limit(g.id, k.name, lo, hi, scope)
            msg = f"limited {k.name} to {min(lo, hi):g} to {max(lo, hi):g} ({scope})"
        elif a.cmd == "unlimit":
            msg = f"cleared the limit on {k.name} ({scope})" if ovr.clear(g.id, "limits", k.name, scope) else f"{k.name} had no limit under {scope}"
        elif a.cmd == "undo":
            from .judge import vkey
            st = State()
            st.touch(g.id)
            done = []
            for c, rec in (st.data.get(g.id) or {}).items():
                if not ovr.scope_matches(scope, c):
                    continue
                _a, _k, _b, _c, jj, _o = _judge_for(g, c, st)
                bad = jj.best(k.name, base[k.name])
                if bad == base[k.name] and not jj.record(k.name, bad):
                    continue
                ovr.ban(g.id, k.name, vkey(bad), scope)
                rec.get("current", {}).pop(k.name, None)
                done.append(f"{c}: {k.show(bad)} banned, next best {k.show(_judge_for(g, c, st)[4].best(k.name, base[k.name]))}")
            st.save()
            msg = ("undone: " + "; ".join(done)) if done else f"nothing learned for {k.name} under {scope}"
        elif a.cmd == "unban":
            from .judge import vkey
            v = _value_for(k, a.value)
            msg = f"{k.name} = {v} allowed again ({scope})" if ovr.clear(g.id, "banned", k.name, scope, value_key=vkey(v)) else f"{k.name} = {v} was not undone under {scope}"
        else:
            st = State()
            st.touch(g.id)
            n = 0
            for c, rec in (st.data.get(g.id) or {}).items():
                if ovr.scope_matches(scope, c):
                    n += int(rec.get("values", {}).pop(k.name, None) is not None)
                    rec.get("current", {}).pop(k.name, None)
                    rec.get("pressure", {}).pop(k.name, None)
                    if rec.get("focus") == k.name:
                        rec["focus"] = None
            st.save()
            msg = f"forgot what he learned for {k.name} under {n} set(s) of conditions ({scope}): back to your value {k.show(base[k.name])}"
        journal.write("override", goal=g.id, action=a.cmd, knob=k.name, scope=scope, detail=msg)
        print(msg)
    elif a.cmd == "priority":
        if a.order:
            unknown = [x for x in a.order if x not in goals]
            if unknown:
                raise SystemExit(f"unknown goal(s): {', '.join(unknown)} (known: {', '.join(goals)})")
            order = spec.set_priority(a.order)
        else:
            order = spec.priority()
        for i, gid in enumerate(order, 1):
            g = goals[gid]
            print(f"  {i}. {gid:12s} {g.title} ({g.kind})")
        if spec.ranks_above("walls", "ball_punt"):
            print("walls rank above the punt: he never chases the ball closer to a wall than chase_wall_in")
    elif a.cmd == "practise":
        from .practice import choose, score_goals
        for c in score_goals():
            print(f"  {c.goal.id:12s} {c.score:.2f}  {c.sentence}")
        g, sentence = choose(" ".join(["practise"] + a.words))
        print("he would say:", sentence)
    elif a.cmd == "verdict":
        from . import overrides as ovr
        from .approach import Outcome
        from .journal import conditions_key
        g = _goal(goals, a.goal)
        journal = Journal()
        rows = journal.read()
        cond_of = {r["session"]: conditions_key(r.get("conditions") or {}) for r in rows if r.get("kind") == "session_start" and r.get("goal") == g.id}
        scope = _scope(a)
        hits = [r for r in rows if r.get("kind") == "attempt" and r.get("goal") == g.id and r.get("number") == a.number and ovr.scope_matches(scope, cond_of.get(r.get("session"), ""))]
        conds = sorted({cond_of.get(r["session"], "") for r in hits})
        if not hits:
            raise SystemExit(f"no counted attempt #{a.number} for {g.id} under {scope}")
        if len(conds) > 1:
            raise SystemExit(f"attempt #{a.number} exists under {', '.join(conds)}: add --floor or --scope to say which")
        row, cond = hits[-1], conds[0]
        before = [v for v in rows if v.get("kind") == "verdict" and v.get("session") == row["session"] and v.get("index") == row["index"]]
        was = before[-1]["verdict"] if before else None
        o = row["outcome"]
        outcome = Outcome(o["code"], o["score"], o["success"], o.get("text", ""), stages=o.get("stages"))
        st = State()
        _a, _k, _b, _c, j, _ov = _judge_for(g, cond, st)
        live = st.for_goal(g.id, cond)
        j.state = live                                                        # change the stored record itself
        for kk, vv in (("values", {}), ("pressure", {}), ("settled", []), ("banned", {}), ("current", {}), ("suggestions", {})):
            live.setdefault(kk, vv)
        live.setdefault("count", 0)
        changed = ""
        if a.verdict == "wrong" and was != "wrong":
            j.retract(outcome, row["settings"])
            changed = "taken out of his records"
        elif a.verdict == "right" and was == "wrong":
            j._learn(a.number, outcome, row["settings"])
            live["count"] += 1
            changed = "put back into his records"
        st.save()
        journal.write("verdict", goal=g.id, session=row["session"], index=row["index"], number=a.number, conditions=cond, verdict=a.verdict, scored=o["code"], note=a.note)
        print(f"attempt #{a.number} ({cond}, scored {o['code']}): {a.verdict}" + (f"; {changed}" if changed else ""))
    elif a.cmd == "curate":
        from . import curate as cu
        if a.mac_history:
            out = cu.prune_mac_history(a.mac_history, a.dry)
        elif a.restore:
            from ..config import settings
            from ..memory.store import Store
            out = cu.restore(Store(settings.memory_db_path), a.dry)
        else:
            out = cu.curate(dry=a.dry)
        print(("DRY RUN, nothing changed:\n" if a.dry else "") + ("\n".join(f"  {x}" for x in out) if out else "nothing to do"))
    elif a.cmd == "overrides":
        from . import overrides as ovr
        for line in ovr.describe(a.goal) or ["no overrides"]:
            print(line)
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
    elif a.cmd == "lesson":
        from ..config import settings
        from ..memory import review
        from ..memory.store import Store
        from .journal import LESSON_SOURCE
        store = Store(settings.memory_db_path)
        if a.action == "add":
            text = " ".join(a.args).strip()
            if not text:
                raise SystemExit("usage: g2goal lesson add TEXT")
            print("lesson saved" if store.add_fact(text, importance=2, core=False, source=LESSON_SOURCE) else "not saved (empty, a near-duplicate, or it names a date or time)")
        else:
            if not a.args or not a.args[0].isdigit():
                raise SystemExit(f"usage: g2goal lesson {a.action} ID" + (" TEXT" if a.action == "edit" else ""))
            fid = int(a.args[0])
            row = next((f for f in store.list_facts() if f["id"] == fid), None)
            if row is None or row["source"] != LESSON_SOURCE:
                raise SystemExit(f"no goal lesson #{fid} (only lessons G2 saved from goal sessions can be changed here)")
            if a.action == "edit":
                text = " ".join(a.args[1:]).strip()
                if not text:
                    raise SystemExit("usage: g2goal lesson edit ID TEXT")
                print(f"lesson #{fid} rewritten" if store.update_fact(fid, text) else "not changed (the same text is already another fact)")
            else:
                review.delete_record(settings.memory_db_path, "facts", fid)
                print(f"lesson #{fid} moved to the review Trash")
    elif a.cmd == "reset":
        if not a.yes:
            raise SystemExit("this forgets what the goal learned (the journal is kept): add --yes")
        print("forgotten" if State().reset(a.goal) else "nothing was learned for it")


if __name__ == "__main__":
    main(sys.argv[1:])
