"""Take, label and manage wall pictures on the Pi (replaces the one-off helper used on 2026-10-10).

    python -m pi_pipeline.vision.wall_pictures shot --label wall_straight --inches 16 [--angle 0] [--note TEXT] [--set NAME]
    python -m pi_pipeline.vision.wall_pictures list
    python -m pi_pipeline.vision.wall_pictures delete 7 [8 ...]

`shot` stands G2 (the eased stand-up), waits until the IMU shows he has stopped swaying (camera shake), warms the camera up and meters the light, takes the picture, retakes it once if it is
badly exposed (brightness outside 85 to 140, or more than 2% blown out), rests him, and saves `shot_NNN.jpg` plus a line in `labels.json` in `~/g2_wall_pics` (`G2_WALL_PICS_DIR`): the label,
the distance in INCHES from the camera lens to the base of the wall, the angle, the exposure, whether he was still, whether it was retaken, and the estimator's raw rows. Pictures stay on the
Pi and the Mac cache; never in the repo. The voice service holds the camera and the serial port: stop it first (`bash tools/g2_safe_stop.sh voice`), start it again afterwards.
The labels are what `wall_distance pictures` builds the calibration from and `wall_replay` checks the steering against."""
from __future__ import annotations

import argparse
import json
import re
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_DIR = os.path.expanduser(os.environ.get("G2_WALL_PICS_DIR", "~/g2_wall_pics"))


def load_labels(folder) -> dict:
    try:
        return json.loads((Path(folder) / "labels.json").read_text())
    except (OSError, ValueError):
        return {}


def next_shot_number(folder) -> int:
    nums = [int(p.stem.split("_")[1]) for p in Path(folder).glob("shot_*.jpg") if p.stem.split("_")[1].isdigit()]
    return max(nums, default=0) + 1


def record(folder, n: int, info: dict) -> None:
    labels = load_labels(folder)
    labels[f"shot_{n:03d}"] = info
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / "labels.json").write_text(json.dumps(labels, indent=1))


def _refuse_calibration(folder, owner_instructed: bool = False) -> bool:
    """Refuse a calibration set unless the owner instructed this move (owner, 2026-11-26: trash and restore are allowed on his instruction, `--owner-instructed`; delete and empty-trash never are).
    Returns True when the set is a calibration set and the move is allowed: the caller then unlocks the set's files first and re-seals it (manifest and read-only) after."""
    from .wall_calibration_set import is_calibration_dir
    if not is_calibration_dir(folder):
        return False
    if not owner_instructed:
        raise SystemExit(f"{folder} is a wall calibration set: its pictures are never deleted by this tool, and are trashed or restored only on the owner's instruction (--owner-instructed); they are what the calibration is built from")
    return True


def _unseal(folder) -> None:
    from .wall_calibration_set import unlock_file
    for f in (Path(folder) / "labels.json", Path(folder) / "_trash" / "labels.json"):
        unlock_file(f)


def _reseal(folder) -> None:
    from . import wall_calibration_set as wcs
    wcs.write_manifest(folder)
    wcs.lock(folder)


def delete(folder, numbers) -> list:
    _refuse_calibration(folder)                      # never on a calibration set, even on instruction: a delete is permanent
    labels = load_labels(folder)
    gone = []
    for n in numbers:
        name = f"shot_{int(n):03d}"
        for ext in (".jpg", ".json"):
            f = Path(folder) / (name + ext)
            if f.exists():
                f.unlink()
                gone.append(f.name)
        labels.pop(name, None)
    (Path(folder) / "labels.json").write_text(json.dumps(labels, indent=1))
    return gone


def _ring_dir() -> Path:
    from .wall_distance import PICS_DIR
    return Path(PICS_DIR)


def trash(folder, names, owner_instructed: bool = False) -> list:
    """Move wall pictures to a trash folder (nothing is erased): `shot_021` (a recognition shot: the picture, its sidecar and its labels entry) or `ring/wall_....jpg` (a roam picture). Returns the names moved.
    A calibration set only on the owner's instruction (`owner_instructed`): the move is made, then the set's manifest is rewritten and its files locked again."""
    cal = _refuse_calibration(folder, owner_instructed)
    if cal:
        _unseal(folder)
    folder, ring = Path(folder), _ring_dir()
    labels, moved = load_labels(folder), []
    tdir = folder / "_trash"
    tl = {}
    try:
        tl = json.loads((tdir / "labels.json").read_text())
    except (OSError, ValueError):
        pass
    for name in names:
        if name.startswith("ring/"):
            f = ring / Path(name).name
            dst = ring.with_name(ring.name + "_trash") / f.name
            if f.exists() and f.suffix == ".jpg":
                dst.parent.mkdir(parents=True, exist_ok=True)
                f.replace(dst)
                moved.append(name)
            continue
        stem = Path(name).stem
        if not re.fullmatch(r"shot_\d+", stem):
            continue
        tdir.mkdir(parents=True, exist_ok=True)
        hit = False
        for ext in (".jpg", ".json"):
            f = folder / (stem + ext)
            if f.exists():
                f.replace(tdir / f.name)
                hit = True
        if stem in labels:
            tl[stem] = labels.pop(stem)
            hit = True
        if hit:
            moved.append(stem)
    if tdir.exists():
        (tdir / "labels.json").write_text(json.dumps(tl, indent=1))
    (folder / "labels.json").write_text(json.dumps(labels, indent=1))
    if cal:
        _reseal(folder)
    return moved


def restore(folder, names, owner_instructed: bool = False) -> list:
    cal = _refuse_calibration(folder, owner_instructed)
    if cal:
        _unseal(folder)
    folder, ring = Path(folder), _ring_dir()
    labels, back = load_labels(folder), []
    tdir = folder / "_trash"
    try:
        tl = json.loads((tdir / "labels.json").read_text())
    except (OSError, ValueError):
        tl = {}
    for name in names:
        if name.startswith("ring/"):
            src = ring.with_name(ring.name + "_trash") / Path(name).name
            if src.exists():
                ring.mkdir(parents=True, exist_ok=True)
                src.replace(ring / src.name)
                back.append(name)
            continue
        stem = Path(name).stem
        for ext in (".jpg", ".json"):
            f = tdir / (stem + ext)
            if f.exists():
                f.replace(folder / f.name)
                back.append(stem) if stem not in back else None
        if stem in tl:
            labels[stem] = tl.pop(stem)
    if tdir.exists():
        (tdir / "labels.json").write_text(json.dumps(tl, indent=1))
    (folder / "labels.json").write_text(json.dumps(labels, indent=1))
    if cal:
        _reseal(folder)
    return back


def empty_trash(folder) -> int:
    _refuse_calibration(folder)
    """The only permanent delete of a wall picture (the page's Empty trash): the recognition trash and the roam trash. Returns how many pictures were removed."""
    import shutil
    n = 0
    for tdir in (Path(folder) / "_trash", _ring_dir().with_name(_ring_dir().name + "_trash")):
        if tdir.exists():
            n += len(list(tdir.glob("*.jpg")))
            shutil.rmtree(tdir)
    return n


def best_picture(take, still=None):
    """`take(prep)` -> a snapshot or None. Warm-up on, one retake when badly exposed, keep the better. Returns (snapshot, retaken)."""
    from .exploration_pictures import _badly_exposed, _exposure_cost
    snap = take(True)
    if snap is None:
        return None, False
    if _badly_exposed(snap.jpeg):
        again = take(True)
        if again is not None and _exposure_cost(again.jpeg) < _exposure_cost(snap.jpeg):
            return again, True
        return snap, True
    return snap, False


def shot(args) -> int:
    if subprocess.run(["systemctl", "is-active", "--quiet", "g2-voice"]).returncode == 0 and not args.force:
        print("the voice service is running and holds the camera and the serial port: bash tools/g2_safe_stop.sh voice first (or --force)")
        return 2
    os.environ["G2_SHUTTER"] = "off"                                 # the snapshot's own click is a background thread that this short-lived command would cut off: it plays the click itself, to the end, below
    from ..config import settings
    from ..gait.stillness import StillnessWaiter
    from ..link.serial_link import SerialLink
    from .snapshot import CameraSnapshotter, exposure_stats
    from . import wall_calibration_set as wcs
    folder = wcs.set_dir(args.calibration) if args.calibration else Path(args.dir)
    folder.mkdir(parents=True, exist_ok=True)
    n = next_shot_number(folder)
    lk = SerialLink("/dev/serial0", baud=115200)
    if not lk.connect():
        print("could not open the serial port")
        return 2
    cam = None
    rested = False
    try:
        lk.send("gP", read_reply=False, settle=0.0)                  # the 5 Hz IMU print the stillness wait reads
        cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump,
                                exposure_check=True, idle_close_s=0)
        if not args.stay:
            import threading
            cam.snapshot()                                           # warm the camera up while he is still lying down
            keep = threading.Event()

            def _keep_answering():                                   # the camera drops the first request after a pause: `send("kup")` below plays the whole eased stand-up (about 5 seconds, it returns when he is up), so throwaway frames keep it answering and the real picture follows at once
                while not keep.is_set():
                    if cam.snapshot() is None:
                        time.sleep(0.2)
            th = threading.Thread(target=_keep_answering, daemon=True)
            th.start()
            sent_at = time.monotonic()
            try:
                lk.send("kup", read_reply=False, settle=0.0)         # the eased K-skill stand-up, played by the link: it returns when he stands (a wait added after it was extra standing: owner, 2026-11-26, the servos sagged before the picture)
            finally:
                keep.set()
            stood_at = time.monotonic()
            print(f"the stand-up call took {stood_at - sent_at:.1f} s")
            th.join(timeout=1.5)
        if args.stay:
            still = StillnessWaiter(lk.poll_imu).wait(timeout_s=6.0)
            snap, retaken = best_picture(lambda prep: cam.snapshot())
        else:                                                        # standing picture: at most 1 second after the rise (a short stillness check), ONE picture (no retake: more standing), then he lies down at once
            still = StillnessWaiter(lk.poll_imu).wait(timeout_s=1.0)
            snap, retaken = cam.snapshot(), False
        stood_s = None
        if not args.stay:                                            # standard protocol for a standing picture (owner, 2026-11-26): start from rest, warm the camera up, stand, take the picture, lie down at once; everything after this (saving, the estimator, the beep) happens with him at rest
            stood_s = round(time.monotonic() - stood_at, 1)
            if snap is not None:
                try:
                    from ..voice import shutter
                    shutter.play(wait=True)                          # the click is about 0.13 s: played to the end so it is always heard (the background version was not heard on 2026-11-26); the click means the picture is taken, so it sounds BEFORE he lies down (owner, 2026-11-26: it came after the rest and looked like a late picture)
                except Exception:  # noqa: BLE001
                    pass
            end_quiet = getattr(lk, "_end_quiet", None)              # the link stays silent behind a skill until its completion echo (up to 10 s) and held this krest back about 5 seconds (command log 2026-11-26 11:22:34 up, 11:22:41 krest): ensure_rest ends that silence first, so do the same
            if callable(end_quiet):
                end_quiet()
            lk.send("krest", read_reply=False, settle=0.0)           # the lie-down starts NOW (ensure_rest first read the joints for about 8 seconds before sending it: command log 2026-11-26 11:18:43 stand, 11:18:55 krest); the finally block below confirms the rest pose
        if snap is None:
            print("no picture (the camera did not answer)")
            return 1
        path = folder / f"shot_{n:03d}.jpg"
        path.write_bytes(snap.jpeg)
        st = exposure_stats(snap.jpeg)
        info = {"label": args.label, "distance_in": args.inches, "angle_deg": args.angle, "note": args.note or "", "set": (f"calibration:{args.calibration}" if args.calibration else args.set), "still": still, "retaken": retaken,
                "exposure": None if st is None else {"mean": round(st.mean, 1), "clip_high": round(st.clip_high, 4)}, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "stood_s": stood_s}
        try:
            from .embedder import to_image
            from .wall_distance import base_rows
            rows, _ = base_rows(to_image(snap.jpeg))
            info["base_rows"] = [None if r is None else round(r, 3) for r in rows]
        except Exception as e:  # noqa: BLE001
            info["estimator_error"] = repr(e)
        if args.calibration:                                     # a calibration picture: the camera and arm state go with it, the set is hashed and locked read-only
            try:
                from ..attachments import current as _att
                info["attachment"] = _att()
            except Exception:  # noqa: BLE001
                pass
            wcs.unlock_file(folder / "labels.json")
        record(folder, n, info)
        if args.calibration:
            wcs.write_manifest(folder)
            wcs.lock(folder)
        at = f" at {args.inches} in" if args.inches is not None else ""
        if args.stay:
            try:
                from ..voice import shutter
                shutter.play(wait=True)                                # you hear the picture was taken (user, 2026-11-01: "I didn't hear a beep")
            except Exception:  # noqa: BLE001
                pass
        if args.label == "look" and args.inches is None:
            print("NOTE: saved with the default label 'look' and no distance. For a calibration picture run e.g. `g2look wall_straight 12`.")
        print(f"saved {path.name}: {args.label}{at}; still={still} retaken={retaken} exposure={info['exposure']} stood_s={info['stood_s']}")
        return 0
    finally:
        try:
            if cam is not None:
                cam.close()
        except Exception:  # noqa: BLE001
            pass
        if not args.stay and not rested:
            from ..behavior.ball_chase import ensure_rest
            ensure_rest(lk)                                          # lie down in the rest position, confirmed, servos relaxed (already done right after the picture when it was taken)
        lk.send("gp", read_reply=False, settle=0.0)
        lk.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shot")
    s.add_argument("--label", required=True, help="wall_straight | wall_far | wall_angle_left | wall_angle_right | corner | door | rug_edge | chair_leg | box | mirror | ...")
    s.add_argument("--inches", type=float, default=None, help="distance from the camera lens to the base of the wall (or the thing), in inches; left out = not known (g2look)")
    s.add_argument("--angle", type=float, default=0.0, help="degrees the body is rotated from square to the wall (left negative)")
    s.add_argument("--note", default="")
    s.add_argument("--set", default="exposure-checked")
    s.add_argument("--calibration", default=None, metavar="NAME", help="a CALIBRATION picture: saved in its own protected set ~/g2_wall_calibration/NAME (never mixed with the roam pictures or the ordinary shots, hashed, read-only), for the wall calibration; give --inches")
    s.add_argument("--force", action="store_true")
    s.add_argument("--stay", action="store_true", help="G2 is already standing and stays standing: no stand-up before, no lying down after (faster; the person repositions him between pictures)")
    sub.add_parser("list")
    v = sub.add_parser("verify", help="re-hash a calibration set and say what changed")
    v.add_argument("name")
    d = sub.add_parser("delete")
    d.add_argument("numbers", nargs="+", type=int)
    sub.add_parser("empty-trash")
    for nm in ("trash", "restore"):
        t = sub.add_parser(nm)
        t.add_argument("names", nargs="+")
        t.add_argument("--owner-instructed", action="store_true", help="the owner told me to move pictures of a calibration set (use --dir ~/g2_wall_calibration/SET); the set is re-hashed and locked after")
    a = ap.parse_args(argv)
    if a.cmd == "shot":
        if a.calibration and a.inches is None:
            raise SystemExit("a calibration picture needs --inches: the measured distance from the camera lens to the base of the wall")
        return shot(a)
    if a.cmd == "verify":
        from . import wall_calibration_set as wcs
        res = wcs.verify(wcs.set_dir(a.name))
        print(json.dumps(res))
        return 0 if res["ok"] else 1
    if a.cmd == "list":
        for k, v in sorted(load_labels(a.dir).items()):
            e = v.get("exposure") or {}
            print(f"{k}  {v.get('label'):18s} {str(v.get('distance_in')):>6s} in  angle {v.get('angle_deg')}  set {v.get('set')}  still={v.get('still')} mean={e.get('mean')}")
        return 0
    if a.cmd == "empty-trash":
        print(json.dumps({"removed": empty_trash(a.dir)}))
        return 0
    if a.cmd in ("trash", "restore"):
        print(json.dumps({"moved" if a.cmd == "trash" else "restored": (trash if a.cmd == "trash" else restore)(a.dir, a.names, owner_instructed=a.owner_instructed)}))
        return 0
    print("deleted:", ", ".join(delete(a.dir, a.numbers)) or "nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
