"""Replay saved wall pictures through the wall estimator and the steering logic, at the desk (user, 2026-10-10: test steering changes without G2).

    python -m pi_pipeline.vision.wall_replay DIR [--cal PATH]

DIR holds `shot_NNN.jpg` and a `labels.json` (see `wall_pictures.py`). For every picture with a label it prints the true distance, what the estimator reads (nearest wall and the five
column groups, in inches), the state, and what an exploring G2 would DO with that look (nothing / turn left or right / oof, back up and turn around), and whether the turn side
matches the picture's `expected_turn` when it has one. Each picture is judged as if it were the second of two looks that agree, so a one-off glare reading is not tested here (that is
covered by unit tests). Nothing moves; no hardware is used."""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from .wall_distance import AHEAD_GROUPS, CAL_PATH, groups_within, IN_TO_CM, NEAR_IN, TURN_IN, Calibration, WallReading, estimate, state_of


def decide(reading: WallReading) -> str:
    """What an exploring G2 does with this look: "none", "turn left/right (wall ahead)", or "oof, back up, turn left/right"."""
    from ..behavior import BehaviorDriver, DriverInputs, EffectKind
    from ..behavior.chirps import ChirpMood
    from ..personality.traits import BehaviorParams

    class Clk:
        t = 1000.0

        def __call__(self):
            return self.t
    clk = Clk()
    d = BehaviorDriver(BehaviorParams(), clock=clk, rng=random.Random(0), chirps=True)
    clk.t += 11
    d.tick(DriverInputs(arm_explore=True, frame=[]))
    clk.t += 1
    reading.t = clk.t - 0.5
    tick = d.tick(DriverInputs(frame=[], wall=reading))
    moods = [e.payload for e in tick.effects if e.kind is EffectKind.CHIRP]
    turns = [float(e.payload) for e in tick.effects if e.kind is EffectKind.TURN]
    if ChirpMood.HIT in moods:
        clk.t += 4.0
        later = d.tick(DriverInputs(frame=[]))                         # the back-up is on the way; the turn-around comes after it
        for _ in range(8):
            clk.t += 0.5
            later = d.tick(DriverInputs(frame=[]))
            turns += [float(e.payload) for e in later.effects if e.kind is EffectKind.TURN]
        side = "right" if turns and turns[-1] > 0 else "left"
        return f"oof, back up, turn {side}"
    if turns:
        return f"turn {'right' if turns[0] > 0 else 'left'} (wall ahead)"
    return "none"


def replay(pictures_dir: str, cal: Calibration | None = None, labels: dict | None = None) -> list:
    from .embedder import to_image
    cal = cal or Calibration.load()
    if cal is None:
        raise SystemExit(f"no calibration at {CAL_PATH}: build one first (python -m pi_pipeline.vision.wall_distance pictures DIR ...)")
    labels = labels if labels is not None else json.loads((Path(pictures_dir) / "labels.json").read_text())
    rows = []
    for name, info in sorted(labels.items()):
        jpg = Path(pictures_dir) / f"{name}.jpg"
        if not jpg.exists():
            continue
        est = estimate(to_image(jpg.read_bytes()), cal)
        near_groups = groups_within(est, TURN_IN)
        nearest = None if est.nearest_cm is None else round(est.nearest_cm / IN_TO_CM, 1)
        reading = WallReading(0.0, state_of(est), nearest, est.turn, True, near_groups, 3 if near_groups >= AHEAD_GROUPS else 0)
        action = decide(reading)
        exp = info.get("expected_turn")
        side_ok = None if not exp or "turn" not in action else (exp in action)
        rows.append({"shot": name, "label": info.get("label"), "true_in": info.get("distance_in"), "nearest_in": nearest, "state": reading.state,
                     "groups_in": [None if c is None else round(c / IN_TO_CM, 1) for c in est.group_cm], "action": action, "expected_turn": exp, "side_ok": side_ok})
    return rows


def replay_roam(roam_dir: str, roam_labels: dict, cal: Calibration | None = None) -> list:
    """The roam pictures G2 kept at near looks (`ring/wall_*.jpg`) and what you labelled them in the Walls tab (`roam_labels.json`, keys like `ring/wall_..._near.jpg`): the label `nothing` says there was no
    wall within about a foot, so the right action is none. Same columns as `replay`."""
    from .embedder import to_image
    cal = cal or Calibration.load()
    rows = []
    for key, info in sorted(roam_labels.items()):
        jpg = Path(roam_dir) / key
        if not jpg.exists():
            continue
        est = estimate(to_image(jpg.read_bytes()), cal)
        near_groups = groups_within(est, TURN_IN)
        nearest = None if est.nearest_cm is None else round(est.nearest_cm / IN_TO_CM, 1)
        reading = WallReading(0.0, state_of(est), nearest, est.turn, True, near_groups, 3 if near_groups >= AHEAD_GROUPS else 0, clamped=bool(getattr(est, "clamped", False)))
        rows.append({"shot": key, "label": info.get("label"), "true_in": info.get("distance_in"), "nearest_in": nearest, "state": reading.state, "action": decide(reading),
                     "groups_in": [None if c is None else round(c / IN_TO_CM, 1) for c in est.group_cm]})
    return rows


def score(shot_rows: list, roam_rows: list) -> dict:
    """How a detector scores: of the calibration shots that are walls (labels `wall_*`) with a known distance, how many it ACTS on by distance band (a wall within 24 in should be acted on, one farther should not),
    and of the roam pictures labelled `nothing`, how many it wrongly acts on (the false alarms)."""
    walls = [r for r in shot_rows if str(r["label"]).startswith("wall") and r["true_in"] is not None]
    acts = lambda r: r["action"] != "none"  # noqa: E731
    bands = {"within 12 in": [r for r in walls if r["true_in"] <= 12], "13 to 24 in": [r for r in walls if 12 < r["true_in"] <= 24], "farther than 24 in": [r for r in walls if r["true_in"] > 24]}
    nothing = [r for r in roam_rows if str(r["label"]).lower() == "nothing"]
    return {"wall acted on": {k: f"{sum(acts(r) for r in v)} of {len(v)}" for k, v in bands.items()}, "false alarms (labelled nothing, acted on)": f"{sum(acts(r) for r in nothing)} of {len(nothing)}",
            "false alarm shots": [r["shot"] for r in nothing if acts(r)]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    ap.add_argument("--cal", default=None)
    ap.add_argument("--score", action="store_true", help="DIR is the wall picture folder (shot_*.jpg, labels.json, ring/, roam_labels.json): score the detector on the calibration shots and on the roam pictures you labelled `nothing`")
    a = ap.parse_args(argv)
    cal = Calibration.load(a.cal) if a.cal else None
    if a.score:
        shots = replay(a.dir, cal)
        roam = replay_roam(a.dir, json.loads((Path(a.dir) / "roam_labels.json").read_text()), cal) if (Path(a.dir) / "roam_labels.json").exists() else []
        for k, v in score(shots, roam).items():
            print(f"{k}: {v}")
        return 0
    rows = replay(a.dir, cal)
    print(f"{'shot':9s} {'label':22s} {'true in':>7s} {'reads in':>8s} {'state':8s} {'groups (in)':34s} action")
    for r in rows:
        ok = "" if r["side_ok"] is None else ("  [side ok]" if r["side_ok"] else f"  [WRONG SIDE, expected {r['expected_turn']}]")
        print(f"{r['shot']:9s} {str(r['label']):22s} {str(r['true_in'] if r['true_in'] is not None else '-'):>7s} {str(r['nearest_in'] if r['nearest_in'] is not None else '-'):>8s} {r['state']:8s} {str(r['groups_in']):34s} {r['action']}{ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
