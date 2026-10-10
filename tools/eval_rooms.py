#!/usr/bin/env python3
"""Phase P0 of the place memory plan (docs/plan-detail/place-memory-plan.md): can a picture's room be told from the other rooms' pictures? Run on the Mac over the pulled pictures
(`g2pics pull`) after giving the pictures a room in the review page (`g2pics`, the Room button; the labels are in <root>/rooms.json).

    python tools/eval_rooms.py [--root DIR] [--embedder histogram] [--embedder onnx:/path/model.onnx] [--window 3] [--gate 0.75]

A picture is classified by the rooms of the pictures most like it: a room's score is the mean of its `--topk` best similarities. Pictures taken within `--same-stop-s` seconds of the one being
tested are left out of the comparison (they are the same stop, so they would flatter the result), and so is the picture itself. Three numbers per embedder:
  single      one picture alone, tested against everything else that is not the same stop;
  session     the same, but also leaving out every picture of the same day/session (the honest test of a returning visit; only rooms seen in 2+ sessions);
  vote        `--window` consecutive stops of one session vote together (their score vectors are added), the way G2 would use the last few survey stops.
The gate is the `vote` accuracy on the `session` test (or on `single` while no room has been seen on 2+ days). Nothing is written and nothing is downloaded.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pi_pipeline.vision.embedder import make_embedder  # noqa: E402


def _when(sidecar: Path, jpg: Path) -> datetime | None:
    try:
        return datetime.strptime(json.loads(sidecar.read_text())["time"], "%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, KeyError):
        return None


def load(root: Path):
    """[(jpg path, room, datetime)] for every decodable survey / named picture with a room and a time, sorted by time."""
    from PIL import Image
    try:
        rooms = json.loads((root / "rooms.json").read_text())
    except (OSError, ValueError):
        return [], 0, 0
    items, undecodable, untimed = [], 0, 0
    for f in sorted(list((root / "survey").glob("*/*.jpg")) + list((root / "named").glob("*/*.jpg"))):
        room = rooms.get(f.name)
        if not room:
            continue
        try:
            Image.open(f).load()
        except OSError:
            undecodable += 1                      # cut off by the camera
            continue
        t = _when(f.with_suffix(".json"), f)
        if t is None:
            untimed += 1
            continue
        items.append((f, room, t))
    items.sort(key=lambda x: x[2])
    return items, undecodable, untimed


def _scores(i, items, vec, roomset, same_stop_s, topk, leave_session):
    """{room: score} for item i against the others; a room with nothing left to compare is missing."""
    f, _room, t = items[i]
    by = defaultdict(list)
    for j, (g, r, u) in enumerate(items):
        if j == i or abs((u - t).total_seconds()) <= same_stop_s or (leave_session and u.date() == t.date()):
            continue
        by[r].append(float(vec[f] @ vec[g]))
    return {r: float(np.mean(sorted(s, reverse=True)[:topk])) for r, s in by.items() if r in roomset}


def evaluate(spec, items, same_stop_s, topk, window):
    emb = make_embedder(spec)
    vec = {f: emb.embed(f.read_bytes()) for f, _, _ in items}
    rooms = sorted({r for _, r, _ in items})
    days = defaultdict(set)
    for _, r, t in items:
        days[r].add(t.date())
    multi = {r for r in rooms if len(days[r]) >= 2}
    res = {}
    for mode in ("single", "session"):
        sess = mode == "session"
        scored = []                                        # (index, {room: score})
        for i, (_f, r, _t) in enumerate(items):
            if sess and r not in multi:
                continue
            s = _scores(i, items, vec, set(rooms) if not sess else multi, same_stop_s, topk, sess)
            if r in s and len(s) >= 2:
                scored.append((i, s))
        ok = sum(max(s, key=s.get) == items[i][1] for i, s in scored)
        conf = Counter((items[i][1], max(s, key=s.get)) for i, s in scored)
        # vote: windows of `window` consecutive scored pictures of one day whose true room is the same
        votes = tot = 0
        by_day = defaultdict(list)
        for i, s in scored:
            by_day[items[i][2].date()].append((i, s))
        for seq in by_day.values():
            for k in range(0, max(0, len(seq) - window + 1)):
                w = seq[k:k + window]
                if len({items[i][1] for i, _ in w}) != 1:
                    continue
                acc = defaultdict(float)
                for _, s in w:
                    for r, v in s.items():
                        acc[r] += v
                tot += 1
                votes += max(acc, key=acc.get) == items[w[0][0]][1]
        res[mode] = dict(n=len(scored), acc=ok / len(scored) if scored else None, conf=conf, vote_n=tot, vote=votes / tot if tot else None)
    return emb.name, rooms, days, res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/g2_pictures/explore"))
    ap.add_argument("--embedder", action="append", default=None)
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--window", type=int, default=3)
    ap.add_argument("--same-stop-s", type=float, default=120.0)
    ap.add_argument("--gate", type=float, default=0.75)
    a = ap.parse_args(argv)
    items, bad, untimed = load(Path(a.root))
    counts = Counter(r for _, r, _ in items)
    if len(counts) < 2:
        print(f"need pictures in at least 2 rooms under {a.root} (rooms.json holds {len(counts)} with usable pictures): give the pictures a room in the review page (g2pics, Room button)")
        return 1
    print(f"{len(items)} pictures with a room: " + ", ".join(f"{r} {n}" for r, n in sorted(counts.items())) + (f"; left out {bad} cut-off, {untimed} without a time" if bad or untimed else ""))
    f = lambda v: "n/a" if v is None else f"{v:.0%}"       # noqa: E731
    passed = None
    for spec in (a.embedder or ["histogram"]):
        name, rooms, days, res = evaluate(spec, items, a.same_stop_s, a.topk, a.window)
        print(f"\n{name}   (rooms seen on 2+ days: {', '.join(r for r in rooms if len(days[r]) >= 2) or 'none yet'})")
        for mode, label in (("single", "one picture, other stops"), ("session", "one picture, other days only")):
            r = res[mode]
            print(f"  {mode:8} {label:30} {f(r['acc']):>5} of {r['n']:<3}   {a.window}-stop vote {f(r['vote']):>5} of {r['vote_n']}")
            wrong = [(t, p, n) for (t, p), n in sorted(r["conf"].items()) if t != p]
            if wrong:
                print("           mistakes (true -> guessed): " + ", ".join(f"{t}->{p} x{n}" for t, p, n in wrong))
        key = res["session"] if res["session"]["vote"] is not None else res["single"]
        passed = key["vote"] is not None and key["vote"] >= a.gate
        print(f"  gate: {a.window}-stop vote on the {'session' if key is res['session'] else 'single'} test {f(key['vote'])} vs {a.gate:.0%}: {'PASS' if passed else 'not yet'}"
              + ("" if res["session"]["vote"] is not None else "   (no room seen on 2+ days yet: this is the easy test)"))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
