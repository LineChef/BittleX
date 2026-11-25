#!/usr/bin/env python3
"""Check the tub and puck finders against every saved picture, and show what a change to a finder changes (read-only; nothing is moved, sent or deleted).

    python tools/g2_finder_regress.py [--root ~/Desktop/G2Memory/g2_pictures] [--set tub] [--pictures DIR ...] [--no-negatives]
                                      [--save FILE] [--compare FILE]

It reads each picture with the CURRENT code (`basket_finder.find_basket_array`, `puck_finder.find_puck_array` with the tub in the picture, `find_puck_in_tub_array`) and prints:
  * the recognition set (default `tub`, labelled and hash-pinned: calibration data is read, never written): the tub found in how many pictures and with what mean distance error against the label, the pictures that should show a puck inside (label has "inside") and were read, and any "puck inside" read on a picture whose label says it is not;
  * negatives (the wall pictures, the older cylinder and basket set, the wall calibration sets: no tub in them): how many the tub finder wrongly reads as a tub;
  * every extra folder given with --pictures (a run's copied pictures): what each picture reads.
`--save FILE` writes every picture's reading as JSON; `--compare FILE` lists the pictures whose reading differs from that snapshot: run it before and after a finder change, and a real tub or puck that stops reading, or a new false one, shows at once (the 2026-11-25 check of 144 pictures, made by hand four times). The picture folders show the home: this never copies or prints picture content, only readings.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def read_picture(rgb) -> dict:
    """What the finders read in one decoded picture: the tub, the puck on the floor (with the tub in the picture) and the puck inside the tub; each None or a short tuple."""
    from pi_pipeline.vision import basket_finder as bf
    from pi_pipeline.vision import puck_finder as pf
    tub = bf.find_basket_array(rgb)
    puck = pf.find_puck_array(rgb, tub, by="width")
    inside = pf.find_puck_in_tub_array(rgb, tub) if tub is not None else None
    return {"tub": None if tub is None else [round(tub.claw_in, 1), round(tub.bearing_deg, 1), tub.width_px],
            "puck": None if puck is None else [round(puck.claw_in, 1), round(puck.bearing_deg, 1), puck.width_px, puck.height_px],
            "inside": None if inside is None else [inside.count, inside.width_px, inside.height_px]}


def read_file(path: str) -> dict | None:
    from pi_pipeline.vision.ball_finder import _decode
    with open(path, "rb") as f:
        rgb = _decode(f.read())
    return None if rgb is None else read_picture(rgb)


def compare(old: dict, new: dict) -> list[tuple]:
    """(picture, old reading, new reading) for each picture present in both whose reading changed, and each one only in one of them."""
    out = []
    for k in sorted(set(old) | set(new)):
        if old.get(k) != new.get(k):
            out.append((k, old.get(k), new.get(k)))
    return out


def judge_set(readings: dict, labels: dict) -> dict:
    """Score a labelled tub set: `readings` is {picture stem: read_picture(...)}, `labels` the set's labels.json (label, distance_in)."""
    found, n, errs, inside_ok, inside_n, inside_false = 0, 0, [], 0, 0, []
    for stem, r in readings.items():
        lab = labels.get(stem) or {}
        label = str(lab.get("label", ""))
        n += 1
        if r["tub"] is not None:
            found += 1
            d = lab.get("distance_in")
            if d is not None:
                errs.append(r["tub"][0] - float(d))
        should = "8in_inside" in label
        if should:
            inside_n += 1
            inside_ok += 1 if r["inside"] is not None else 0
        elif r["inside"] is not None and "inside" not in label:
            inside_false.append((stem, label, r["inside"]))
    return {"pictures": n, "tub_found": found, "mean_error_in": round(sum(errs) / len(errs), 2) if errs else None, "inside_expected": inside_n, "inside_read": inside_ok, "inside_false": inside_false}


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=os.path.expanduser("~/Desktop/G2Memory/g2_pictures"))
    ap.add_argument("--set", default="tub", help="the labelled recognition set to score (under recognition_sets/)")
    ap.add_argument("--pictures", nargs="*", default=[], help="extra folders of .jpg files (a run's copied pictures): print what each reads")
    ap.add_argument("--no-negatives", action="store_true")
    ap.add_argument("--save", default=None)
    ap.add_argument("--compare", default=None)
    a = ap.parse_args(argv)
    allr: dict = {}
    sdir = os.path.join(a.root, "recognition_sets", a.set)
    labels = {}
    if os.path.exists(os.path.join(sdir, "labels.json")):
        labels = json.load(open(os.path.join(sdir, "labels.json")))
    sread = {}
    for f in sorted(glob.glob(os.path.join(sdir, "shot_*.jpg"))):
        r = read_file(f)
        if r is not None:
            sread[os.path.basename(f)[:-4]] = r
            allr[f"{a.set}/{os.path.basename(f)}"] = r
    if sread:
        j = judge_set(sread, labels)
        print(f"set {a.set}: {j['pictures']} pictures; the tub read in {j['tub_found']}, mean distance error {j['mean_error_in']} in; a puck inside read in {j['inside_read']} of {j['inside_expected']} that have one at 8 in; "
              f"{len(j['inside_false'])} puck-inside read(s) on a picture not labelled inside")
        for stem, label, v in j["inside_false"]:
            print(f"  FALSE inside: {stem} ({label}): {v}")
    if not a.no_negatives:
        neg = (sorted(glob.glob(os.path.join(a.root, "wall", "shot_*.jpg"))) + sorted(glob.glob(os.path.join(a.root, "recognition_sets", "cylinder_basket", "shot_*.jpg")))
               + sorted(glob.glob(os.path.join(a.root, "wall_calibration", "*", "*.jpg"))))[:400]
        false = 0
        for f in neg:
            r = read_file(f)
            if r is None:
                continue
            allr[os.path.relpath(f, a.root)] = r
            false += 1 if r["tub"] is not None else 0
        print(f"negatives (no tub in them): {len(neg)} pictures, the tub finder reads a tub in {false}")
    for d in a.pictures:
        for f in sorted(glob.glob(os.path.join(os.path.expanduser(d), "*.jpg"))):
            r = read_file(f)
            if r is None:
                continue
            allr[f"{os.path.basename(os.path.normpath(d))}/{os.path.basename(f)}"] = r
            print(f"  {os.path.basename(f)}: tub {r['tub']} puck {r['puck']} inside {r['inside']}")
    if a.save:
        json.dump(allr, open(a.save, "w"), indent=0, sort_keys=True)
        print(f"saved {len(allr)} readings to {a.save}")
    if a.compare:
        old = json.load(open(a.compare))
        diff = compare(old, allr)
        print(f"compared with {a.compare}: {len(diff)} reading(s) changed of {len(set(old) | set(allr))}")
        for k, o, n in diff:
            print(f"  {k}: {o}  ->  {n}")


if __name__ == "__main__":
    main()
