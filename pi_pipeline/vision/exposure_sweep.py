"""Measure how the camera's exposure target (`ae_bump`) changes a scene's brightness, to calibrate the exposure check (vision/snapshot.py).

    python -m pi_pipeline.vision.exposure_sweep --label bright --out /tmp/ae      # lamp on
    python -m pi_pipeline.vision.exposure_sweep --label dark   --out /tmp/ae      # lamp off

Holds the camera still, tries each exposure offset in turn (letting auto-exposure settle, discarding one frame), and prints the mean
brightness plus the share of blown-out and crushed pixels. Saves each frame as <out>/ae_<label>_<offset>.jpg so they can be compared by eye.
Stop the voice service first if it is holding the camera (it releases it after 2 minutes idle)."""
from __future__ import annotations

import argparse
import logging
import os
import time

from ..config import settings
from .snapshot import CameraSnapshotter, exposure_stats

OFFSETS = (-24, -8, 0, 16, 32, 48, 64)


def sweep(label: str, out: str) -> None:
    os.makedirs(out, exist_ok=True)
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=0, exposure_check=False,
                            idle_close_s=0)
    print(f"{label}: offset   mean  blown-out  crushed")
    with cam._lock:
        cam._open()
        for bump in OFFSETS:
            cam._apply_ae(bump)
            cam._bump = bump
            time.sleep(1.2)
            cam._grab_one()                                   # let auto-exposure settle; this frame is discarded
            frame = cam._grab_one()
            st = exposure_stats(frame.jpeg) if frame else None
            if frame is None or st is None:
                print(f"{label}:  {bump:+4d}   no picture")
                continue
            with open(os.path.join(out, f"ae_{label}_{bump:+d}.jpg"), "wb") as f:
                f.write(frame.jpeg)
            print(f"{label}:  {bump:+4d}  {st.mean:5.1f}   {100 * st.clip_high:5.1f}%   {100 * st.clip_low:5.1f}%", flush=True)
    cam.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", default="/tmp/ae")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    sweep(args.label, args.out)


if __name__ == "__main__":
    main()
