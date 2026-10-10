#!/usr/bin/env python3
"""Timing estimates for training runs, read from what the trainer already writes (read-only: nothing here touches a runner, a log or a checkpoint).

    python tools/eta.py now  [--target 20e6] [--tail final20m|stage|MIN]   # the run in progress: pace of its last ~1M steps -> 'training done' and 'verdict' clocks
    python tools/eta.py plan --steps 3e6 [--tail ...]                       # a run not started yet: median seconds per step of similar finished runs
    python tools/eta.py check                                               # what the runners' own 'done about' lines promised vs what happened

Source of truth is the SB3 table in each run's console log (`trained/*_console.log`: `total_timesteps` and `time_elapsed`), which every run of this project prints.
History is only runs since the native-arm switch (build stamp 2026-10-08 14:28; older logs are Rosetta-slow). The pace is NOT constant: a 20M run goes from ~4500 to
~2400 steps/s, so a plan uses similar-sized runs' whole-run average, and `now` scales a finished run's shape to this run's speed, with an honest range (short by up to ~40% early in a long run in the one backtest so far). Fewer than 2 comparable runs -> it says so and prints no number.
Add about 20% by hand when something heavy runs on the Mac alongside the run (trackers and tests share its CPU)."""
import argparse
import glob
import os
import re
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TRAINED = os.path.join(HERE, "..", "rl_training", "opencat-gym", "trained")
ARM_SINCE = time.mktime((2026, 10, 8, 14, 28, 0, 0, 0, -1))       # native arm64 venv: older logs are not comparable
TAILS = {                                                          # minutes after training ends until the VERDICT; hand-kept, measured in the V6 chain (2026-10-09)
    "stage": 3,        # tracker/benchmark scoring of a chain stage
    "screen": 3,       # a 3M screen is scored once
    "final20m": 15,    # final scoring 6 + averaged candidate 6 + report, export, promotion check
}
STARTUP_MIN = 1.5      # process start, env build and checkpoint save around a run (console time_elapsed does not include it)


def read_pairs(path, tail_bytes=600_000):
    """(total_timesteps, time_elapsed) pairs from the tail of a console log, oldest first. SB3 prints them as '|    key   | value |' table rows."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - tail_bytes))
            text = f.read().decode("utf8", "replace")
    except OSError:
        return []
    pairs, el = [], None
    for line in text.splitlines():
        m = re.match(r"\|\s*(time_elapsed|total_timesteps)\s*\|\s*(\d+)", line)
        if not m:
            continue
        if m.group(1) == "time_elapsed":
            el = int(m.group(2))
        elif el is not None:
            pairs.append((int(m.group(2)), el))
            el = None
    return pairs


def finished_runs(trained=TRAINED, min_steps=1e6, now=None):
    """[(name, steps, seconds)] of runs since the arm switch whose log is not being written any more and which reached `min_steps`."""
    now = now or time.time()
    out = []
    for p in glob.glob(os.path.join(trained, "*_console.log")):
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt < ARM_SINCE or now - mt < 600:
            continue
        pairs = read_pairs(p)
        if pairs and pairs[-1][0] >= min_steps:
            out.append((os.path.basename(p)[:-12], pairs[-1][0], pairs[-1][1]))
    return out


def clock(minutes_from_now):
    return time.strftime("%I:%M %p", time.localtime(time.time() + 60 * minutes_from_now)).lstrip("0")


def tail_minutes(arg):
    if arg is None:
        return None
    return float(arg) if re.fullmatch(r"[\d.]+", arg) else TAILS[arg]


def cmd_plan(steps, tail, trained=TRAINED):
    runs = [r for r in finished_runs(trained) if 0.5 * steps <= r[1] <= 2.2 * steps]
    if len(runs) < 2:
        print(f"not enough history for a {steps:.0f}-step run: {len(runs)} comparable finished run(s) since the arm switch (need 2). No estimate given.")
        return 1
    per_step = sorted(s / n for _, n, s in runs)
    med = statistics.median(per_step)
    lo, hi = per_step[len(per_step) // 4], per_step[-1 - len(per_step) // 4]
    t = lambda sps: sps * steps / 60 + STARTUP_MIN                                            # noqa: E731
    print(f"basis: {len(runs)} finished runs of 0.5-2.2x this size ({', '.join(n for n, _, _ in runs[-5:])}); median {med * 1e6 / 60:.1f} min per million steps")
    print(f"training: about {t(med):.0f} min (range {t(lo):.0f}-{t(hi):.0f}), done about {clock(t(med))} if started now")
    tm = tail_minutes(tail)
    if tm is not None:
        print(f"verdict: about {t(med) + tm:.0f} min ({tm:.0f} min of scoring/report after training), about {clock(t(med) + tm)} (range {clock(t(lo) + tm)}-{clock(t(hi) + tm)})")
    return 0


def cmd_now(target, tail, trained=TRAINED):
    logs = sorted(glob.glob(os.path.join(trained, "*_console.log")), key=os.path.getmtime)
    live = [p for p in logs if time.time() - os.path.getmtime(p) < 600]
    if not live:
        print("no run is writing a console log right now (nothing modified in the last 10 minutes).")
        return 1
    path = live[-1]
    pairs = read_pairs(path)
    if len(pairs) < 3:
        print(f"{os.path.basename(path)}: too few progress rows yet to measure a pace.")
        return 1
    steps, elapsed = pairs[-1]
    ref = next((p for p in pairs if steps - p[0] <= 1e6), pairs[0])            # the oldest row within the last ~1M steps
    if steps - ref[0] < 1e5 or elapsed <= ref[1]:
        print("too little progress to measure a pace.")
        return 1
    pace = (elapsed - ref[1]) / (steps - ref[0])
    print(f"run: {os.path.basename(path)[:-12]}  at {steps / 1e6:.1f}M steps, {elapsed / 60:.0f} min in; recent pace {1 / pace:.0f} steps/s ({pace * 1e6 / 60:.1f} min per million)")
    if target is None:
        print("give --target (e.g. 20e6) for the finish time.")
        return 0
    name = os.path.basename(path)[:-12]
    left_pace = max(target - steps, 0) * pace / 60
    ratios = shape_ratios(steps, elapsed, target, trained, exclude=name)
    if ratios:
        left = elapsed * statistics.median(ratios) / 60 - elapsed / 60                  # progress-aligned: same shape as finished runs of this size, scaled by this run's own speed
        print(f"basis: {len(ratios)} finished run(s) of this size as the shape (pace slows as a run goes on); recent pace alone would say {left_pace:.0f} min")
    else:
        left = left_pace
        print("basis: recent pace only (no finished run of this size to take the shape from); it slows by roughly 10% per 5M steps, so treat this as the early end of the range")
    frac = steps / target
    late = 0.6 if frac < 0.15 else 0.4 if frac < 0.35 else 0.3 if frac < 0.6 else 0.15      # backtest on the V6 20M: the estimate was 41% short at 10% progress, 28% at 25%, 21% at 50%, 2-14% at 75%
    print(f"training done in about {left:.0f}-{left * (1 + late):.0f} min, about {clock(left)} to {clock(left * (1 + late))}")
    tm = tail_minutes(tail)
    if tm is not None:
        print(f"verdict about {clock(left + tm)} to {clock(left * (1 + late) + tm)} ({tm:.0f} min of scoring/report after training)")
    return 0


def shape_ratios(steps, elapsed, target, trained=TRAINED, exclude=None):
    """For each finished run of about the target's size: its total time divided by the time it had used at `steps`. Scales a reference run's shape to this run's speed."""
    out = []
    for name, n, total in finished_runs(trained, min_steps=0.5 * target):
        if name == exclude or not (0.5 * target <= n <= 2.2 * target):
            continue
        pairs = read_pairs(os.path.join(trained, name + "_console.log"), tail_bytes=10**9)
        at = next((e for st, e in pairs if st >= steps), None)
        if at and at > 0:
            out.append(total * target / n / at)                                        # total time scaled to the target size
    return out


def cmd_check(trained=TRAINED):
    """Promised vs actual from the runners' own logs: 'START ... about N min' against the next DONE/FINISHED line of the same tag (log timestamps are '[v6 08:31 PM]')."""
    rows = []
    for p in sorted(glob.glob(os.path.join(trained, "phase_v*.log"))):
        lines = open(p, errors="replace").read().splitlines()
        for i, l in enumerate(lines):
            m = re.match(r"\[v\d (\d\d:\d\d [AP]M)\] (\S+) START:.*?about (\d+) min", l)
            if not m:
                continue
            for l2 in lines[i + 1:]:
                if re.match(r"\[v\d \d\d:\d\d [AP]M\] " + re.escape(m.group(2)) + r" START:", l2):
                    break                                        # restarted before it finished: that START never completed
                m2 = re.match(r"\[v\d (\d\d:\d\d [AP]M)\] " + re.escape(m.group(2)) + r" (DONE|FINISHED)", l2)
                if m2:
                    t0, t1 = (time.strptime(x, "%I:%M %p") for x in (m.group(1), m2.group(1)))
                    got = ((t1.tm_hour * 60 + t1.tm_min) - (t0.tm_hour * 60 + t0.tm_min)) % 1440
                    rows.append((os.path.basename(p), m.group(2), int(m.group(3)), got))
                    break
    if not rows:
        print("no START/DONE pairs found in trained/phase_v*.log: the log format may have changed, so this check cannot judge anything.")
        return 1
    for f, tag, est, got in rows[-12:]:
        print(f"{f:16} {tag:22} promised {est:4d} min, took {got:4d} min  ({(got - est) / est * 100:+.0f}%)")
    print("(DONE lines include the stage's scoring, FINISHED lines do not)")
    worst = max(abs(g - e) / e for _, _, e, g in rows[-12:])
    print("drift over 25%: update the runner's minutes (or the TAILS table here)." if worst > 0.25 else "within 25%.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("now")
    n.add_argument("--target", type=float)
    n.add_argument("--tail")
    p = sub.add_parser("plan")
    p.add_argument("--steps", type=float, required=True)
    p.add_argument("--tail")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        return cmd_plan(a.steps, a.tail)
    if a.cmd == "now":
        return cmd_now(a.target, a.tail)
    return cmd_check()


if __name__ == "__main__":
    sys.exit(main())
