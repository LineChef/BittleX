#!/usr/bin/env python3
"""One report for a goal run on G2's Pi: the whole review that was typed by hand after every basket run (read-only; moves nothing, changes nothing on the Pi).

    python tools/g2_goal_run_report.py [--last N] [--goal basket] [--check-finders] [--keep DIR]

Needs G2_PI. For each of the newest N sessions of the goal (default: the newest 1, any goal) it prints:
  * the session line and every attempt (outcome code, score, seconds, the settings used);
  * the goal's own lines from the voice service's journal for that window, with the repeated circle arcs collapsed to one line, plus falls, sags, the board's own moves and the eased lie-down;
  * the camera: how many requests got no answer or were asked again, and the claw look's picture timing;
  * the gaps of more than 12 seconds between his pictures (where he stood waiting) and between his own log lines;
  * the picture log of the run (`~/g2_runs/basket_run/pictures/<run>/pictures.jsonl`): per picture the look time, the tub (inches, bearing, width), a puck on the floor and a puck inside the tub as the finders read them then;
  * with `--check-finders`: the pictures are copied to a scratch folder (deleted afterwards, or kept in DIR) and read again by the finders as they are NOW; a puck-sized coloured blob the puck finder did not read is flagged (the "he looked right at it and did not see it" case).
The logic is in pure functions (`sessions`, `journal_events`, `collapse`, `gaps`, `picture_lines`, `puck_like_blobs`) so it is tested without a Pi.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL = "~/.local/share/g2/goal_journal.jsonl"
PICTURES = "~/g2_runs/basket_run/pictures"
WANT = re.compile(r"g2\.goal|G2:|fell|fall recorded|legs sagged|move gate|forcing it|leg joint|no answer after|gave no picture|asking again|eased lie-down|rest was asked|BiBoard started|stand-up|camera ready|camera: ")
GAP_S = 12


def _t(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def parse_rows(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def sessions(rows: list[dict], goal: str | None = None, last: int = 1) -> list[dict]:
    """The newest `last` finished sessions: {session, goal, start, end, why, attempts: [attempt rows]}."""
    by: dict = {}
    for r in rows:
        k = r.get("kind")
        if k not in ("session_start", "session_end", "attempt"):
            continue
        s = by.setdefault(r.get("session"), {"session": r.get("session"), "goal": r.get("goal"), "start": None, "end": None, "why": None, "attempts": []})
        if k == "session_start":
            s["start"] = r.get("time")
        elif k == "session_end":
            s["end"], s["why"] = r.get("time"), r.get("ended") or r.get("why") or (r.get("summary") or {}).get("ended")
        else:
            s["attempts"].append(r)
    done = [s for s in by.values() if s["end"] and s["start"] and (goal is None or s["goal"] == goal)]
    done.sort(key=lambda s: s["end"])
    return done[-last:]


def journal_events(text: str, year_day: str) -> list[tuple]:
    """(time, text) for the journal lines that matter (WANT), `year_day` being 'YYYY-MM-DD' of the window start. Lines look like 'Nov 25 10:50:54 g2pi python[1]: 10:50:54 g2.goal ...'."""
    out = []
    for line in text.splitlines():
        if not WANT.search(line):
            continue
        m = re.search(r"(\d\d):(\d\d):(\d\d) (.*)$", re.sub(r"^.*?python\[\d+\]:\s*", "", line))
        if m:
            h, mi, s, rest = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        else:
            m2 = re.match(r"\w+ +\d+ (\d\d):(\d\d):(\d\d) \S+ \S+: (.*)$", line)
            if not m2:
                continue
            h, mi, s, rest = int(m2.group(1)), int(m2.group(2)), int(m2.group(3)), m2.group(4)
        out.append((h * 3600 + mi * 60 + s, rest.strip()[:200]))
    return out


def collapse(events: list[tuple]) -> list[tuple]:
    """Repeated lines of the same kind (the circle's arcs, the line-up's scans) become one line with a count: (time, text, count)."""
    out: list = []
    for t, text in events:
        key = re.sub(r"[\d.]+", "#", text)
        if out and out[-1][3] == key and ("wide arc" in text or "pivot scan" in text or "tub out of view" in text):
            out[-1] = (out[-1][0], out[-1][1], out[-1][2] + 1, key, t)
        else:
            out.append((t, text, 1, key, t))
    return [(a, b, c, e) for a, b, c, _k, e in out]


def gaps(times: list[float], limit: float = GAP_S) -> list[tuple]:
    """(from, to, seconds) for each step between consecutive times longer than `limit`."""
    return [(a, b, round(b - a, 1)) for a, b in zip(times, times[1:]) if b - a > limit]


def fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}"


def picture_lines(rows: list[dict]) -> list[str]:
    lines = []
    for r in rows:
        t, p, tp = r.get("tub"), r.get("floor_puck"), r.get("tub_puck")
        tub = "-" if not t else f"{t.get('claw_in'):.1f} in {t.get('bearing_deg'):+.0f} deg {t.get('width_px')} px"
        puck = "-" if not p else f"{p.get('claw_in'):.1f} in {p.get('bearing_deg'):+.0f} deg {p.get('width_px')}x{p.get('height_px')}"
        inside = "-" if not tp else f"{tp.get('count', tp.get('area', '?'))} px {tp.get('width_px', '?')}x{tp.get('height_px', '?')}" if isinstance(tp, dict) else str(tp)
        arc = (r.get("circle") or {}).get("arc")
        lines.append(f"  {r.get('time')} {str(r.get('file') or r.get('label'))[4:] if str(r.get('file', '')).startswith('a01_') else r.get('file')}  look {r.get('look_s')} s  arc {arc}  tub {tub}  puck {puck}  in tub {inside}")
    return lines


def puck_like_blobs(rgb) -> list[tuple]:
    """Compact, strongly coloured floor blobs of a claw-down picture: (pixels, width, height, x, y). The puck finder's own thresholds are not used on purpose: this is what a person would call "a puck is there"."""
    import numpy as np
    sys.path.insert(0, ROOT)
    from pi_pipeline.vision.ball_finder import _blobs
    fl = rgb.astype(float) / 255.0
    mx, mn = fl.max(-1), fl.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    v = mx * 255
    r, g, b = [rgb[..., i].astype(int) for i in range(3)]
    m = (sat >= 0.36) & (v >= 90) & ((r - g) > 22) & ((r - b) > 25)
    m[:60, :] = False
    out = []
    for ys, xs in _blobs(m):
        if len(xs) < 25:
            continue
        w, h = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        if 6 <= w <= 45 and 5 <= h <= 32 and w / h < 3.0:
            out.append((len(xs), w, h, int(xs.mean()), int(ys.mean())))
    return sorted(out, reverse=True)[:3]


def ssh(cmd: str, timeout: int = 90) -> str:
    pi = os.environ.get("G2_PI")
    if not pi:
        raise SystemExit("set G2_PI to user@host of the Pi")
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", pi, cmd], capture_output=True, text=True, timeout=timeout)
    return r.stdout


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--last", type=int, default=1)
    ap.add_argument("--goal", default=None)
    ap.add_argument("--check-finders", action="store_true", help="copy the run's pictures to a scratch folder and read them again with the finders as they are now")
    ap.add_argument("--keep", default=None, help="with --check-finders: keep the copied pictures in this folder (they show the home: never commit them)")
    a = ap.parse_args(argv)
    rows = parse_rows(ssh(f"cat {JOURNAL}"))
    sess = sessions(rows, a.goal, a.last)
    if not sess:
        print("no finished session found")
        return
    for s in sess:
        t0, t1 = _t(s["start"]), _t(s["end"])
        print(f"=== session {s['session']} ({s['goal']}) {s['start']} to {s['end']}: {s['why']}, {len(s['attempts'])} attempt(s)")
        for at in s["attempts"]:
            o = at.get("outcome") or {}
            print(f"  attempt {at.get('number')}: {at.get('ended')} / {o.get('code')} score {o.get('score')} {at.get('seconds')} s  settings {at.get('settings')}")
        since, until = t0.strftime("%Y-%m-%d %H:%M:%S"), t1.strftime("%Y-%m-%d %H:%M:%S")
        text = ""
        for boot in ("", "-b -1"):
            text = ssh(f"journalctl {boot or '-b'} -u g2-voice --no-pager --since '{since}' --until '{until}' | grep -E 'g2.goal|G2:|fell|fall recorded|legs sagged|move gate|forcing it|leg joint|no answer after|gave no picture|asking again|eased lie-down|rest was asked|BiBoard started|stand-up|camera' | cut -c1-230")
            if text.strip():
                break
        ev = journal_events(text, since[:10])
        print("--- the run's own lines (repeats collapsed)")
        for t, line, n, end in collapse(ev):
            if "BiBoard started" in line or "camera grab" in line:
                continue
            print(f"  {fmt(t)}  {line}" + (f"   x{n} until {fmt(end)}" if n > 1 else ""))
        stalls = sum(1 for _t_, x in ev if "no answer after" in x or "gave no picture" in x)
        print(f"--- the camera: {stalls} request(s) with no answer or asked again; the claw look: " + next((x.split("seconds after the look began):")[-1].strip() for _t_, x in ev if "look picture timing" in x), "no timing line"))
        falls = [x for _t_, x in ev if re.search(r"I fell|fall recorded|legs sagged|move gate", x)]
        print("--- falls and sags: " + ("; ".join(falls[:6]) if falls else "none"))
        gl = [t for t, x in ev if "g2.goal" in x]
        for a0, b0, d in gaps(gl):
            print(f"  gap of {d} s between his own log lines {fmt(a0)} and {fmt(b0)}")
        pics = ssh(f"for d in $(ls -t {PICTURES} | head -8); do h=$(head -c 400 {PICTURES}/$d/pictures.jsonl 2>/dev/null | head -1 | cut -c1-80); echo \"$d $h\"; done")
        stamp = None
        for line in pics.splitlines():
            parts = line.split(None, 1)
            m = re.match(r"(\d{8})_(\d{6})$", parts[0]) if parts else None
            if m:
                d = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
                if t0 <= d <= t1:
                    stamp = parts[0]
                    break
        if stamp is None:
            print("--- no picture folder for this session")
            continue
        prows = parse_rows(ssh(f"cat {PICTURES}/{stamp}/pictures.jsonl"))
        print(f"--- pictures {stamp}: {len(prows)}")
        for line in picture_lines(prows):
            print(line)
        times = []
        for r in prows:
            try:
                h, mi, se = [int(x) for x in str(r.get("time")).split(":")]
                times.append(h * 3600 + mi * 60 + se)
            except ValueError:
                pass
        for a0, b0, d in gaps(times):
            print(f"  gap of {d} s between pictures {fmt(a0)} and {fmt(b0)}")
        if a.check_finders:
            tmp = a.keep or tempfile.mkdtemp(prefix="g2_run_pics_")
            os.makedirs(tmp, exist_ok=True)
            subprocess.run(["scp", "-q", f"{os.environ['G2_PI']}:g2_runs/basket_run/pictures/{stamp}/*.jpg", tmp], capture_output=True)
            sys.path.insert(0, ROOT)
            from pi_pipeline.vision import puck_finder as pf
            from pi_pipeline.vision.ball_finder import _decode
            print("--- the finders read again as they are now (a flagged picture has a puck-sized coloured blob the puck finder did not read)")
            for fn in sorted(os.listdir(tmp)):
                if not fn.endswith(".jpg"):
                    continue
                rgb = _decode(open(os.path.join(tmp, fn), "rb").read())
                if rgb is None:
                    continue
                p = pf.find_puck_array(rgb, None, by="width")
                blobs = puck_like_blobs(rgb)
                if p is None and blobs:
                    print(f"  FLAG {fn}: puck finder reads nothing; puck-like blobs (pixels, w, h, x, y): {blobs}")
                elif p is not None:
                    print(f"  {fn}: puck {p.claw_in:.1f} in {p.bearing_deg:+.0f} deg")
            if not a.keep:
                shutil.rmtree(tmp, ignore_errors=True)
                print("(the copied pictures were deleted)")


if __name__ == "__main__":
    main()
