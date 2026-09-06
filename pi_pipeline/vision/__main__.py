"""Exercise the vision pipeline against a mock detection feed. No hardware.

    python -m pi_pipeline.vision demo            # an object approaching dead ahead
    python -m pi_pipeline.vision demo --bearing 0.2   # ...from the left
    python -m pi_pipeline.vision serial /dev/ttyAMA1  # real feed (hardware)
"""
from __future__ import annotations

import argparse
import logging

from ..config import settings
from .avoidance import ACTION_SKILL, Avoider, AvoidanceAction
from .feed import MockDetectionFeed, SerialDetectionFeed
from .scene import summarize


def _run(feed) -> None:
    avoider = Avoider()
    try:
        for i, frame in enumerate(feed.frames()):
            action = avoider.decide(frame)
            skill = ACTION_SKILL.get(action)
            tag = f" -> {action.value}" + (f" (skill: {skill})" if skill else "")
            if action is not AvoidanceAction.NONE:
                tag = tag.upper()
            print(f"frame {i:>3}: {summarize(frame)}{tag}")
    except KeyboardInterrupt:
        pass
    finally:
        feed.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="pi_pipeline.vision")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--bearing", type=float, default=0.5, help="0=left .. 1=right")
    d.add_argument("--steps", type=int, default=10)
    s = sub.add_parser("serial")
    s.add_argument("port")
    args = ap.parse_args()

    if args.cmd == "demo":
        script = MockDetectionFeed.approaching(steps=args.steps, bearing=args.bearing)
        _run(MockDetectionFeed(script))
    elif args.cmd == "serial":
        _run(SerialDetectionFeed(
            args.port, settings.vision_serial_baud,
            frame_px=settings.vision_frame_px, labels=settings.vision_labels,
            sensor_opt=settings.vision_sensor_opt, ae_bump=settings.vision_ae_bump,
        ))


if __name__ == "__main__":
    main()
