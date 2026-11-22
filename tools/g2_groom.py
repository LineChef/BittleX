#!/usr/bin/env python3
"""Weekly gallery grooming (2026-11-17, owner-approved): keep the picture galleries from growing without end.

    python tools/g2_groom.py [--apply] [--session | --weekly]

The galleries are groomed from an ALLOWLIST, never an exclusion list: only the folders named in TARGETS are ever touched, and anything that could be a calibration picture is refused twice over (a folder name
with a calibration word, and a picture named in any labels or calibration file beside it). Calibration pictures (the wall shots, the wall ring, lift, step and claw calibration, the localizer check, anything with
a labels file) are never touched. Hand-named and promoted pictures are never touched either.

  * CAP: each auto-saved class under explore/named (the chase's green ball pictures) keeps its best CLASS_CAP pictures (picture_score.choose: quality, near-duplicates, spread over distance and bearing).
  * NEAR-DUPLICATES: the behaviour picture folders (bout, watch, stream, seen, contact, explore/survey) keep the best of each group of near-twins.

A dry run by default: a report in ~/Desktop/G2Memory/_dedup_reports/. `--apply` MOVES the extras to ~/Desktop/G2Memory/_pruned/groom_<date>/ (nothing is deleted at once); the groomed-away pictures are deleted
for good only after PURGE_DAYS; the Pi's own trash is purged the same way (a queued `purge-trash --days 14`, so anything trashed there more than 14 days ago is deleted there for good). An apply also caps the training classes under promoted/. `--session` is the start of every hardware session (the hw-session skill); `--weekly` runs only when 7 days have passed. Both apply only when ~/.local/share/g2/groom.json says {"apply": true} (the owner switches it on). An apply also QUEUES the same removal for the Pi (the review page's queue, tools/g2_review_queue.py: the Pi's own restorable trash, sent at once when the Pi answers), so a sync cannot bring the pictures back; only the explore folders have that path, the rest are report only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pi_pipeline.vision import picture_score as ps  # noqa: E402

ROOT = "~/Desktop/G2Memory/g2_pictures"
CAP_CLASSES = ("explore/named",)                                              # each class folder under these is capped
NEAR_DUP_FOLDERS = ("bout", "watch", "stream", "seen", "contact", "explore/survey")
CAL_WORDS = ("cal", "wall", "ring", "localizer", "labels", "claw", "calib", "recog")      # a folder or file with any of these is calibration or recognition data: refused
AUTO_NAMED_BY = ("ball_chase",)                                               # only pictures the robot saved by itself in a named class are groomed; a hand or voice name protects a picture
PURGE_DAYS = 14
APPLY_MAP = {"explore": "pi_pipeline.vision.exploration_pictures", "bout": "pi_pipeline.vision.claw_pictures", "watch": "pi_pipeline.vision.claw_pictures",
             "stream": "pi_pipeline.vision.claw_pictures", "seen": "pi_pipeline.vision.claw_pictures", "contact": "pi_pipeline.vision.claw_pictures"}      # folder -> the Pi module whose restorable `trash` removes the same pictures
APPLY_FOLDERS = tuple(APPLY_MAP)
STATE = "~/.local/share/g2/groom_last"
CONFIG = "~/.local/share/g2/groom.json"
PRUNED = "~/Desktop/G2Memory/_pruned"
REPORTS = "~/Desktop/G2Memory/_dedup_reports"


def is_calibration(path: str, root: str) -> bool:
    """True when the picture could be a calibration or recognition picture: refused whatever else says it is fine."""
    rel = os.path.relpath(path, root).lower()
    if any(w in part for part in rel.split(os.sep) for w in CAL_WORDS):
        return True
    folder = os.path.dirname(path)
    name = os.path.splitext(os.path.basename(path))[0]
    if name.startswith("session_"):                                                  # the hand-taken calibration sessions (a ball at a known distance, the no-ball examples): never groomed
        return True
    for f in os.listdir(folder):
        low = f.lower()
        if low.endswith(".json") and ("label" in low or "cal" in low):
            try:
                if name in open(os.path.join(folder, f)).read():
                    return True
            except OSError:
                return True
    return False


def _named_by(path: str) -> str | None:
    try:
        return json.load(open(os.path.splitext(path)[0] + ".json")).get("named_by")
    except Exception:  # noqa: BLE001
        return None


def _rows(folder: str, root: str) -> list:
    rows = []
    for d, dirs, fs in os.walk(folder):
        for f in fs:
            if not f.lower().endswith((".jpg", ".jpeg")):
                continue
            p = os.path.join(d, f)
            try:
                m = ps.measure(open(p, "rb").read())
            except Exception:  # noqa: BLE001
                m = None
            if m is None:
                continue
            side = _named_by(p)
            rows.append({"file": p, "ok": not ps.reject_reason(m), "why": ps.reject_reason(m), "quality": ps.quality(m, True), "hash": m["hash"], "size": os.path.getsize(p),
                         "protected": is_calibration(p, root) or (os.sep + "named" + os.sep in p and side not in AUTO_NAMED_BY)})
    return rows


def plan(root: str | None = None, cap: int | None = None) -> dict:
    """{target: {"kept": n, "extras": [paths]}} for every allowlisted target. Pure reads."""
    root = os.path.abspath(os.path.expanduser(root or ROOT))
    cap = ps.CLASS_CAP if cap is None else cap
    out = {}
    for top in CAP_CLASSES:
        base = os.path.join(root, top)
        if not os.path.isdir(base):
            continue
        for cls in sorted(os.listdir(base)):
            d = os.path.join(base, cls)
            if os.path.isdir(d):
                rows = _rows(d, root)
                kept, dropped = ps.choose(rows, cap, protected=lambda n, r={x["file"]: x for x in rows}: r[n]["protected"])
                out[f"{top}/{cls}"] = {"kept": len(kept), "extras": sorted(dropped)}
    for top in NEAR_DUP_FOLDERS:
        d = os.path.join(root, top)
        if not os.path.isdir(d):
            continue
        rows = _rows(d, root)
        free = [r for r in rows if not r["protected"] and r["ok"]]
        reps: list = []
        for r in sorted(free, key=lambda r: -r["quality"]):
            for g in reps:
                if ps.hamming(r["hash"], g[0]["hash"]) <= ps.DEDUP_HAMMING:
                    g.append(r)
                    break
            else:
                reps.append([r])
        out[top] = {"kept": len(rows) - sum(len(g) - 1 for g in reps), "extras": sorted(r["file"] for g in reps for r in g[1:])}
    for t in out.values():                                                      # the last line of defence: nothing calibration, nothing outside the allowlist, ever moves
        t["extras"] = [p for p in t["extras"] if not is_calibration(p, root)]
    return out


def apply(result: dict, root: str | None = None, queue: bool = True) -> dict:
    """Move the extras of the folders that have a Pi removal path aside and queue the same removal for the Pi (its trash: restorable, nothing is deleted there). The other folders are report only.
    Returns {"moved": n, "queued": n, "report_only": n}."""
    root = os.path.abspath(os.path.expanduser(root or ROOT))
    dest = os.path.expanduser(f"{PRUNED}/groom_{time.strftime('%Y%m%d')}")
    moved, rels, only = 0, [], 0
    for key, t in result.items():
        top = key.split("/")[0]
        if top not in APPLY_FOLDERS:
            only += len(t["extras"])
            continue
        for p in t["extras"]:
            assert p.startswith(root + os.sep) and not is_calibration(p, root), p
            for src in (p, os.path.splitext(p)[0] + ".json"):
                if os.path.exists(src):
                    to = os.path.join(dest, os.path.relpath(src, root))
                    os.makedirs(os.path.dirname(to), exist_ok=True)
                    shutil.move(src, to)
            moved += 1
            rels.append((APPLY_MAP[top], os.path.relpath(p, os.path.join(root, top if top == "explore" else ""))))      # explore: the path under the Pi's explore_pictures; the claw folders: <kind>/<kind>_<time>/pic under ~/g2_claw_pics minus the kind folder
    queued = 0
    if queue and rels:
        import g2_review_queue as rq                                              # tools/ is on the path: the review page's queue, the one that sends edits to the Pi
        for module in sorted({m for m, _ in rels}):
            mine = [r for m, r in rels if m == module]
            if module.endswith("claw_pictures"):
                mine = [r.split("/", 1)[1] if "/" in r else r for r in mine]            # Mac: bout/bout_<time>/pic.jpg  ->  Pi: bout_<time>/pic.jpg under ~/g2_claw_pics
            for i in range(0, len(mine), 40):
                rq.add(module, ["trash"] + mine[i:i + 40], text=f"gallery grooming: trash {len(mine[i:i + 40])} extra pictures on the Pi too")
                queued += len(mine[i:i + 40])
        try:
            print("   Pi:", rq.apply().get("message"))                            # sent now when the Pi answers; otherwise it stays queued for the next sync
        except Exception as e:  # noqa: BLE001
            print("   Pi: the removal stays queued:", e)
    return {"moved": moved, "queued": queued, "report_only": only}


PI_PURGE_MODULES = ("pi_pipeline.vision.exploration_pictures", "pi_pipeline.vision.claw_pictures")


def queue_pi_purge(days: int = PURGE_DAYS) -> int:
    """Queue the Pi's own trash purge (pictures trashed more than `days` ago are deleted there for good), once per module: an identical entry already waiting is not added again."""
    import g2_review_queue as rq
    waiting = {(e["module"], tuple(e["args"])) for e in rq.pending()}
    n = 0
    for module in PI_PURGE_MODULES:
        args = ("purge-trash", "--days", str(days))
        if (module, args) not in waiting:
            rq.add(module, list(args), text=f"gallery grooming: delete Pi trash older than {days} days")
            n += 1
    return n


def cap_training_classes() -> None:
    """The training classes under promoted/ keep their best CLASS_CAP pictures (tools/curate_class.py --all-promoted): hand-named pictures never, the rest moved aside."""
    import subprocess
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "curate_class.py"), "--all-promoted", "--cap", str(ps.CLASS_CAP), "--apply"], check=False)


def purge(days: int = PURGE_DAYS) -> int:
    """Delete for good the groomed-away folders older than `days` (only groom_<date> folders under _pruned)."""
    base = os.path.expanduser(PRUNED)
    n = 0
    if os.path.isdir(base):
        for name in os.listdir(base):
            p = os.path.join(base, name)
            if name.startswith("groom_") and os.path.isdir(p) and time.time() - os.path.getmtime(p) > days * 86400:
                shutil.rmtree(p)
                n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--weekly", action="store_true")
    ap.add_argument("--session", action="store_true", help="the start-of-session run (hw-session): runs now, applies only when ~/.local/share/g2/groom.json says apply")
    a = ap.parse_args()
    do_apply = a.apply
    if a.session:
        try:
            do_apply = bool(json.load(open(os.path.expanduser(CONFIG))).get("apply"))
        except Exception:  # noqa: BLE001
            do_apply = False
    if a.weekly:
        stamp = os.path.expanduser(STATE)
        if os.path.exists(stamp) and time.time() - os.path.getmtime(stamp) < 7 * 86400:
            return
        try:
            do_apply = bool(json.load(open(os.path.expanduser(CONFIG))).get("apply"))
        except Exception:  # noqa: BLE001
            do_apply = False
    result = plan()
    total = sum(len(t["extras"]) for t in result.values())
    print(f"gallery grooming ({'APPLY' if do_apply else 'dry run'}): {total} extras over {len(result)} targets")
    for k, t in result.items():
        print(f"   {k}: keep {t['kept']}, extras {len(t['extras'])}")
    os.makedirs(os.path.expanduser(REPORTS), exist_ok=True)
    rpt = os.path.expanduser(f"{REPORTS}/groom_{time.strftime('%Y%m%d_%H%M')}.json")
    json.dump(result, open(rpt, "w"), indent=1)
    print(f"   report: {rpt}")
    if do_apply:
        r = apply(result)
        print(f"   moved {r['moved']} pictures aside and queued {r['queued']} for the Pi's trash; {r['report_only']} extras in folders with no Pi removal path stay (report only); purged {purge()} old groomed folder(s)")
        queue_pi_purge()
        try:
            import g2_review_queue as rq
            print("   Pi:", rq.apply().get("message"))                            # the queued removals and the trash purge go now when the Pi answers
        except Exception as e:  # noqa: BLE001
            print("   Pi: stays queued:", e)
        cap_training_classes()
    if a.weekly or a.session:
        os.makedirs(os.path.dirname(os.path.expanduser(STATE)), exist_ok=True)
        open(os.path.expanduser(STATE), "w").write(time.strftime("%Y-%m-%d %H:%M:%S"))


if __name__ == "__main__":
    main()
