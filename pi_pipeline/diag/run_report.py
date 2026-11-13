"""What a batch of normal ball-goal runs shows (owner, 2026-11-09: "I'd prefer to just gather this type of data through running the robot in its normal routines").

Reads the Pi's own logs after the runs (nothing is run on the robot): the goal journal (every attempt's trace), the command log (what the board did on its own), the memory log, the leg check and the motion
events log. Standard library only, so it can be piped to the Pi from the Mac without a deploy:

    ssh <user>@g2pi.local python3 - --attempts 6 < pi_pipeline/diag/run_report.py        # the last 6 ball-goal attempts
    ssh <user>@g2pi.local python3 - --since "2026-11-09 17:40:00" < pi_pipeline/diag/run_report.py

It prints facts and flags, not conclusions: every number comes from the logs, and a flag says what pattern the numbers match.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics as st

G2 = os.path.expanduser("~/.local/share/g2")


def rows(name):
    out = []
    try:
        with open(os.path.join(G2, name)) as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def mean(v):
    return round(st.mean(v), 1) if v else None


def attempts(args):
    a = [r for r in rows("goal_journal.jsonl") if r.get("kind") == "attempt" and r.get("goal") == args.goal]
    if args.since:
        a = [r for r in a if r.get("time", "") >= args.since]
    else:
        a = a[-args.attempts:]
    return a


def still_before(trace, i):
    """Seconds of standing still recorded just before trace entry i (the last `still` entry before it, with nothing between except looks)."""
    for k in range(i - 1, -1, -1):
        e = trace[k]
        if e.get("kind") == "still":
            return e.get("seconds"), e.get("parts")
        if e.get("kind") == "act" and e.get("act") not in ("look",):
            return None, None
    return None, None


def report(args):
    att = attempts(args)
    if not att:
        print("no attempts in that window")
        return
    t0, t1 = att[0].get("time", "?"), att[-1].get("time", "?")
    print(f"== {len(att)} attempt(s), {t0} to {t1}")
    print("\n-- attempts")
    print(f"{'session':9s} {'#':>2s} {'ended':8s} {'secs':>5s} {'pack':>5s}  outcome")
    for a in att:
        o = a.get("outcome") or {}
        print(f"{a.get('session', '?')[:8]:9s} {a.get('index', 0):>2d} {str(a.get('ended')):8s} {a.get('seconds', 0):>5.0f} {str(a.get('pack_pct')):>5s}  {o.get('code')}: {str(o.get('text'))[:70]}")
    ended = collections.Counter(a.get("ended") for a in att)
    codes = collections.Counter((a.get("outcome") or {}).get("code") for a in att)
    print(f"ended: {dict(ended)}   outcomes: {dict(codes)}")

    # ---- falls
    print("\n-- falls (what was happening, and how long he had stood still before)")
    nfall = 0
    for a in att:
        tr = a.get("trace") or []
        for i, e in enumerate(tr):
            if e.get("state") == "fell":
                nfall += 1
                s, parts = still_before(tr, i)
                prev = [x.get("act") for x in tr[max(0, i - 4):i] if x.get("kind") == "act"]
                print(f"  {a.get('time', '?')[11:19]} attempt {a.get('index')}: fell in `{e.get('act') or e.get('kind')}` ({e.get('seconds')} s of it), after {s if s is not None else '?'} s still {parts or ''}; the acts before: {prev}")
    if not nfall:
        print("  none")

    # ---- standing still
    stills = [(e.get("seconds") or 0.0, e.get("before"), e.get("parts") or {}) for a in att for e in (a.get("trace") or []) if e.get("kind") == "still"]
    if stills:
        by = collections.defaultdict(list)
        for sec, before, _ in stills:
            by[before].append(sec)
        total = sum(s for s, _, _ in stills)
        parts = collections.Counter()
        for _, _, p in stills:
            for k, v in p.items():
                parts[k] += v
        print(f"\n-- standing still before a move: {len(stills)} times, {total:.0f} s in all, mean {mean([s for s, _, _ in stills])} s, longest {max(s for s, _, _ in stills):.1f} s")
        print("   by move: " + ", ".join(f"{k} {mean(v)} s (n={len(v)})" for k, v in sorted(by.items(), key=lambda x: -len(x[1]))))
        print("   where the time goes: " + ", ".join(f"{k} {v:.0f} s" for k, v in parts.most_common(6)))

    # ---- line-up (align) turns and turns: did the ball's bearing improve?
    gains = []
    for a in att:
        tr = a.get("trace") or []
        for i, e in enumerate(tr):
            if e.get("kind") == "act" and e.get("act") in ("align", "turn") and e.get("state") == "ok":
                b0 = ((tr[i - 1].get("ball") or {}) if i else {}).get("bearing_deg")
                b1 = next(((x.get("ball") or {}).get("bearing_deg") for x in tr[i + 1:i + 4] if (x.get("ball") or {}).get("bearing_deg") is not None), None)
                if b0 is not None and b1 is not None:
                    gains.append((e.get("act"), abs(b0), abs(b1)))
    if gains:
        for kind in ("align", "turn"):
            g = [(x, y) for k, x, y in gains if k == kind]
            if g:
                better = sum(1 for x, y in g if y < x - 3)
                worse = sum(1 for x, y in g if y > x + 3)
                print(f"\n-- {kind} turns: {len(g)} with a ball seen before and after: {better} brought the ball nearer the middle, {worse} made it worse, {len(g) - better - worse} no change (mean |bearing| {mean([x for x, _ in g])} -> {mean([y for _, y in g])} deg)")

    # ---- walks and turns paces
    meas = collections.defaultdict(list)
    for a in att:
        for e in a.get("trace") or []:
            if e.get("kind") == "measured":
                meas[e.get("what")].append((e.get("seconds"), e.get("value")))
    for what, v in meas.items():
        vals = [x for _, x in v if x is not None]
        weak = [(s, x) for s, x in v if x is not None and x < (0.6 if what == "walk" else 6.0)]
        print(f"\n-- measured {what}: {len(vals)} readings, mean {mean(vals)} {'in/s' if what == 'walk' else 'deg/s'}" + (f"; {len(weak)} barely moved him (e.g. {weak[:3]})" if weak else ""))

    # ---- claw looks
    phases = collections.defaultdict(list)
    n = 0
    for a in att:
        for e in a.get("trace") or []:
            if e.get("kind") == "claw_look" and e.get("phases_s"):
                n += 1
                for k, v in e["phases_s"].items():
                    phases[k].append(v)
    if n:
        tot = sum(mean(v) or 0 for v in phases.values())
        print(f"\n-- claw looks: {n}, about {tot:.0f} s each: " + ", ".join(f"{k} {mean(v)} s" for k, v in phases.items()))

    # ---- what the board did on its own, and the stand-up outcomes
    cmd = [r for r in rows("command_log.jsonl") if t0 <= r.get("t", "") <= (t1[:19] + "z")]
    own = collections.Counter(r.get("line") for r in cmd if r.get("dir") == "board" and r.get("not_from_pi"))
    echo = {"balance", "calib", "rest", "up"}                         # late echoes of the Pi's own commands are flagged the same way
    real = {k: v for k, v in own.items() if k not in ("balance", "calib", "rest")}
    print("\n-- moves the BOARD started on its own (late echoes of our own commands left out): " + (", ".join(f"{k} x{v}" for k, v in real.items()) if real else "none"))
    if "rc" in real or "up" in real:
        print("   FLAG: the board's own self-right (rc / up) ran: the gyro balance was on, or it took a pose for a fall")
    ev = [r for r in rows("motion_events.jsonl") if t0[:19] <= r.get("t", "") <= t1[:19] + "z"]
    if ev:
        kinds = collections.Counter(r.get("event") for r in ev)
        print(f"\n-- motion events: {dict(kinds)}")
        for k in ("stand_up", "attention_entry"):
            rs = [r for r in ev if r.get("event") == k]
            if rs:
                forced = sum(1 for r in rs if r.get("outcome") == "forced")
                refused = sum(1 for r in rs if r.get("outcome") == "refused")
                secs = [r.get("seconds") for r in rs if r.get("seconds") is not None]
                print(f"   {k}: {len(rs)}, mean {mean(secs)} s, longest {max(secs) if secs else '?'} s, {forced} forced, {refused} refused; from: {dict(collections.Counter(r.get('from') for r in rs))}")
                for r in rs:
                    if r.get("outcome") in ("forced", "refused"):
                        print(f"     {r.get('t')}: {k} {r.get('outcome')} from {r.get('from')} after {r.get('seconds')} s")
        off = [r for r in ev if (r.get("max_leg_dev_deg") or 0) >= 8]
        checked = [r for r in ev if r.get("max_leg_dev_deg") is not None]
        if checked:
            print(f"   leg joints against their target after a move: {len(checked)} read, {len(off)} with a joint 8 deg or more off" + ("; firmware gyro balance then: " + str(dict(collections.Counter(r.get("gyro_state") for r in off))) if off else ""))
            for r in off:
                print(f"     {r.get('t')}: {r.get('event')} (from {r.get('from') or r.get('start')}): deviations {r.get('leg_dev_deg')}, gyro balance {r.get('gyro_state')} (before: {r.get('gyro_state_before')})")
    else:
        print("\n-- motion events: none logged (this build does not write them yet: the stand-up outcomes are only on the console)")

    # ---- legs, memory, battery
    lc = [r for r in rows("leg_check.jsonl") if t0[:19] <= r.get("t", "")[:19] <= t1[:19] + "z"]
    if lc:
        bad = [r for r in lc if r.get("bad")]
        print(f"\n-- leg checks after stand-ups: {len(lc)}, {len(bad)} with a leg off its stand angle" + (f"; volts then {[r.get('volts') for r in bad]}" if bad else ""))
    mem = [r for r in rows("memory_log.jsonl") if r.get("kind") == "sample" and t0[:19] <= r.get("t", "")[:19] <= t1[:19] + "z" and "avail_mb" in r]
    if mem:
        lo = min(mem, key=lambda r: r["avail_mb"])
        print(f"\n-- memory: lowest free {lo['avail_mb']:.0f} MB ({lo['t'][11:19]}), peak swap {max(r.get('swap_used_mb', 0) for r in mem):.0f} MB")
    packs = [a.get("pack_pct") for a in att if a.get("pack_pct") is not None]
    if packs:
        print(f"-- pack at attempt starts: {packs[0]}% -> {packs[-1]}%" + ("; the session ended on the battery gate" if any(a.get('ended') == 'battery' for a in att) else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", default="ball_punt")
    ap.add_argument("--attempts", type=int, default=6, help="the last N attempts")
    ap.add_argument("--since", help='only attempts at or after "YYYY-MM-DD HH:MM:SS"')
    report(ap.parse_args())


if __name__ == "__main__":
    main()
