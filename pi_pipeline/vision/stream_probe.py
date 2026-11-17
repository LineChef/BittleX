"""Can the camera module stream pictures continuously? (a camera-only probe, G2 does not move; hardware test, 2026-11-15)

The ball chase and the live follow take one picture per request (`AT+INVOKE=1,0,0`): about 0.35 s each, and the module answers with the previous request's picture, so a follow runs at about 2 pictures a
second and the picture is about 0.9 s old when it is used. The module's continuous mode (`AT+INVOKE=-1,0,1`, the detection feed) runs at about 15 frames a second but carries boxes only. This probe
asks the question the repo has never tried: does `AT+INVOKE=-1,0,0` (loop forever, results WITH the JPEG) stream pictures, and how fast?

It opens the port the way the snapshotter does, starts the loop for `--seconds`, counts what arrives (frames with a picture, frames with boxes only, anything else the module says), prints the rate and the
gaps, saves the first frames, and always sends `AT+BREAK` at the end. The voice service must be stopped (`g2stream`).

    python -m pi_pipeline.vision.stream_probe --seconds 6
"""
from __future__ import annotations

import os
import statistics
import time
from pathlib import Path

LOOP_WITH_PICTURE = b"AT+INVOKE=-1,0,0\r\n"
BREAK = b"AT+BREAK\r\n"
LOCK_AE = b'AT+SETREG="0x3503","0x03"\r\n'      # OV5647: AEC and AGC manual (the exposure and gain stay where auto exposure last left them)
UNLOCK_AE = b'AT+SETREG="0x3503","0x00"\r\n'    # back to automatic


def analyze(arrivals: list[tuple[float, int, int]], other: list[str], seconds: float) -> dict:
    """`arrivals` = (time since start, jpeg bytes, boxes) for each line that carried a picture."""
    ts = [a[0] for a in arrivals]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    return {"seconds": seconds, "pictures": len(arrivals), "pictures_per_s": round(len(arrivals) / seconds, 2) if seconds > 0 else 0.0,
            "first_picture_s": round(ts[0], 2) if ts else None,
            "gap_median_s": round(statistics.median(gaps), 3) if gaps else None, "gap_max_s": round(max(gaps), 3) if gaps else None,
            "jpeg_bytes_mean": round(statistics.mean(a[1] for a in arrivals)) if arrivals else None,
            "with_boxes": sum(1 for a in arrivals if a[2]), "other_lines": len(other), "other_sample": other[:3]}


def brightness_summary(means: list, lock_at: float | None) -> dict:
    """The pictures' mean brightness over the run: how much it swings, and (an exposure-lock experiment) before against after the lock, with the counts and the whole series so a thin split is visible."""
    vals = [m[1] for m in means]
    out = {"mean": round(statistics.mean(vals), 1), "min": min(vals), "max": max(vals), "stdev": round(statistics.pstdev(vals), 2), "series": [[t, v] for t, v in means][:60]}
    if lock_at is not None:
        before = [v for t, v in means if t < lock_at]
        after = [v for t, v in means if t >= lock_at]
        out["n_before_lock"], out["n_after_lock"] = len(before), len(after)
        if before:
            out["before_lock"] = {"mean": round(statistics.mean(before), 1), "stdev": round(statistics.pstdev(before), 2)}
        if after:
            out["after_lock"] = {"mean": round(statistics.mean(after), 1), "stdev": round(statistics.pstdev(after), 2)}
    return out


def run_probe(ser, seconds: float, outdir: Path | None = None, *, clock=time.monotonic, parse=None, sleep=time.sleep, lock_at: float | None = None) -> dict:
    from .snapshot import parse_invoke_line
    parse = parse or parse_invoke_line
    arrivals, other, means = [], [], []
    saved = 0
    locked = False
    try:
        ser.reset_input_buffer()
        ser.write(BREAK)
        sleep(0.2)
        ser.reset_input_buffer()
        ser.write(LOOP_WITH_PICTURE)
        t0 = clock()
        while clock() - t0 < seconds:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", "replace")
            snap = parse(line, [])
            if snap is None:
                if len(other) < 12:
                    other.append(line.strip()[:120])
                continue
            arrivals.append((clock() - t0, len(snap.jpeg), len(snap.detections)))
            if lock_at is not None:                                       # brightness costs a decode per picture: only for the exposure-lock experiment, so a plain rate measurement is not slowed by it (2026-11-17: 2.8 against 4.3 pictures a second)
                try:
                    from .snapshot import exposure_stats
                    st = exposure_stats(snap.jpeg)
                    if st is not None:
                        means.append((round(clock() - t0, 2), round(float(st.mean), 1)))
                except Exception:  # noqa: BLE001
                    pass
            if lock_at is not None and not locked and clock() - t0 >= lock_at:
                ser.write(LOCK_AE)                                         # the experiment: freeze the sensor's auto exposure now (OV5647 0x3503 = manual exposure and gain)
                locked = True
            if outdir is not None and saved < 5:
                saved += 1
                (outdir / f"frame_{saved}.jpg").write_bytes(snap.jpeg)
    finally:
        try:
            ser.write(BREAK)
            if locked:
                ser.write(UNLOCK_AE)                                      # always back to auto exposure
        except Exception:  # noqa: BLE001
            pass
    res = analyze(arrivals, other, seconds)
    if means:
        res["brightness"] = brightness_summary(means, lock_at if locked else None)
    return res


def main() -> None:
    import argparse

    from ..config import settings
    from .snapshot import CameraSnapshotter
    ap = argparse.ArgumentParser(description="Camera-only probe: does AT+INVOKE=-1,0,0 stream pictures, and how fast? (G2 does not move)")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--sensor-opt", type=int, choices=(0, 1, 2), default=0, help="the module's picture size option (0 is what the chase uses)")
    ap.add_argument("--compare", action="store_true", help="run every size option in turn and print the rates side by side (2026-11-16: is 4.3 pictures a second a setting or the module's limit?)")
    ap.add_argument("--lock-ae", action="store_true", help="the exposure-lock experiment: after 2 s of streaming, freeze the sensor's auto exposure and compare the pictures' brightness before and after (restored to auto at the end)")
    args = ap.parse_args()
    outdir = Path(os.path.expanduser(time.strftime("~/g2_claw_pics/stream_%Y%m%d_%H%M%S")))
    outdir.mkdir(parents=True, exist_ok=True)
    for opt in ((0, 1, 2) if args.compare else (args.sensor_opt,)):
        cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=opt, ae_bump=settings.vision_ae_bump, click=False)  # MODE-SPECIFIC(vision/stream_probe.py, 2026-11-15): no shutter click in this look
        try:
            cam._open()                                                # the same start-up the snapshotter does (reset wait, sensor option, exposure)
            res = run_probe(cam._ser, args.seconds, outdir if opt == args.sensor_opt or not args.compare else None, lock_at=2.0 if args.lock_ae else None)
            print(f"STREAM (size option {opt}):", res)
        finally:
            cam.close()
    print(f"PICTURES: {outdir}")


if __name__ == "__main__":
    main()
