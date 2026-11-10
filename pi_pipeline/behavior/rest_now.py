"""Lay G2 in the rest position, confirmed with the board's pose read, then relax the servos: `python -m pi_pipeline.behavior.rest_now`. What the exploration unit runs when it ends (the same verified rest as every
session end: ball_chase.ensure_rest). Exit code 0 when the board read the rest pose, 1 otherwise."""
from __future__ import annotations

import sys
import time


def main() -> int:
    from ..link.serial_link import SerialLink
    from .ball_chase import ensure_rest
    link = SerialLink("/dev/serial0")
    link.connect()
    time.sleep(0.8)
    ok = ensure_rest(link)
    print("rest confirmed" if ok else "rest not confirmed (the pose could not be read as rest)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
