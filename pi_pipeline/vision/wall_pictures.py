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


def delete(folder, numbers) -> list:
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
    from ..config import settings
    from ..gait.stillness import StillnessWaiter
    from ..link.serial_link import SerialLink
    from .snapshot import CameraSnapshotter, exposure_stats
    folder = Path(args.dir)
    folder.mkdir(parents=True, exist_ok=True)
    n = next_shot_number(folder)
    lk = SerialLink("/dev/serial0", baud=115200)
    if not lk.connect():
        print("could not open the serial port")
        return 2
    cam = None
    try:
        lk.send("gP", read_reply=False, settle=0.0)                  # the 5 Hz IMU print the stillness wait reads
        lk.send("kup", read_reply=False, settle=0.0)                 # the eased stand-up
        time.sleep(1.5)
        still = StillnessWaiter(lk.poll_imu).wait(timeout_s=6.0)
        cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump,
                                exposure_check=True, meter_every_s=0.0, idle_close_s=0)
        snap, retaken = best_picture(lambda prep: cam.snapshot())
        if snap is None:
            print("no picture (the camera did not answer)")
            return 1
        path = folder / f"shot_{n:03d}.jpg"
        path.write_bytes(snap.jpeg)
        st = exposure_stats(snap.jpeg)
        info = {"label": args.label, "distance_in": args.inches, "angle_deg": args.angle, "note": args.note or "", "set": args.set, "still": still, "retaken": retaken,
                "exposure": None if st is None else {"mean": round(st.mean, 1), "clip_high": round(st.clip_high, 4)}, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            from .embedder import to_image
            from .wall_distance import base_rows
            rows, _ = base_rows(to_image(snap.jpeg))
            info["base_rows"] = [None if r is None else round(r, 3) for r in rows]
        except Exception as e:  # noqa: BLE001
            info["estimator_error"] = repr(e)
        record(folder, n, info)
        print(f"saved {path.name}: {args.label} at {args.inches} in; still={still} retaken={retaken} exposure={info['exposure']}")
        return 0
    finally:
        try:
            if cam is not None:
                cam.close()
        except Exception:  # noqa: BLE001
            pass
        lk.send("d", read_reply=False, settle=0.0)                   # lie down, servos relaxed
        time.sleep(0.5)
        lk.send("gp", read_reply=False, settle=0.0)
        lk.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shot")
    s.add_argument("--label", required=True, help="wall_straight | wall_far | wall_angle_left | wall_angle_right | corner | door | rug_edge | chair_leg | box | mirror | ...")
    s.add_argument("--inches", type=float, required=True, help="distance from the camera lens to the base of the wall, in inches")
    s.add_argument("--angle", type=float, default=0.0, help="degrees the body is rotated from square to the wall (left negative)")
    s.add_argument("--note", default="")
    s.add_argument("--set", default="exposure-checked")
    s.add_argument("--force", action="store_true")
    sub.add_parser("list")
    d = sub.add_parser("delete")
    d.add_argument("numbers", nargs="+", type=int)
    a = ap.parse_args(argv)
    if a.cmd == "shot":
        return shot(a)
    if a.cmd == "list":
        for k, v in sorted(load_labels(a.dir).items()):
            e = v.get("exposure") or {}
            print(f"{k}  {v.get('label'):18s} {str(v.get('distance_in')):>6s} in  angle {v.get('angle_deg')}  set {v.get('set')}  still={v.get('still')} mean={e.get('mean')}")
        return 0
    print("deleted:", ", ".join(delete(a.dir, a.numbers)) or "nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
