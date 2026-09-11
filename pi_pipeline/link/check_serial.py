"""Serial-link diagnostics for the BiBoard. Needs pyserial + a connected robot.

    python -m pi_pipeline.link.check_serial ports              # list serial ports
    python -m pi_pipeline.link.check_serial ping               # open the configured port, poke it
    python -m pi_pipeline.link.check_serial send kbalance       # send one command, print the reply
    python -m pi_pipeline.link.check_serial skills              # cycle the conversational skill set
    python -m pi_pipeline.link.check_serial rest                # send 'd' (safe state)
    python -m pi_pipeline.link.check_serial firstmove           # guided, confirmed first movement
"""
from __future__ import annotations

import argparse
import logging
import time

from ..config import settings
from ..voice import skills as skillcat
from . import opencat
from .serial_link import SerialLink


def _link() -> SerialLink:
    return SerialLink(settings.serial_port, settings.serial_baud)


# name -> OpenCat servo index (deploy_map.py's confirmed Petoi joint map).
# Head first (index 0, lowest stakes), then the 8 leg servos.
_JOINTS = [
    ("head-pan", 0),
    ("FL-shoulder", 8), ("FR-shoulder", 9), ("BR-shoulder", 10), ("BL-shoulder", 11),
    ("FL-knee", 12), ("FR-knee", 13), ("BR-knee", 14), ("BL-knee", 15),
]


def _firstmove(link: SerialLink, *, deg: float, walk_s: float) -> None:
    """One joint at a time through a small range of motion, each step
    confirmed, before ever trying `kbalance` or a walk gait. Always leaves the
    robot at `d` (rest) on exit, including on Ctrl-C."""
    print(f"Guided first movement -- {deg:g} degree nudge per joint, confirmed each step.")
    print("Enter = do it, s = skip this joint, q = stop here (and rest).\n")
    try:
        for name, idx in _JOINTS:
            choice = input(f"  nudge {name} (servo {idx}) by +{deg:g} deg? [Enter/s/q] "
                          ).strip().lower()
            if choice == "q":
                break
            if choice == "s":
                continue
            link.send(opencat.move_joints([(idx, int(deg))]), read_reply=False)
            after = input(f"    watch it, then Enter to return {name} to neutral "
                         f"(or q to stop here)... ").strip().lower()
            if after == "q":
                break
            link.send(opencat.move_joints([(idx, 0)]), read_reply=False)
        else:
            choice = input("\nAll joints checked. Send kbalance (robot stands)? "
                          "[Enter/q] ").strip().lower()
            if choice != "q":
                link.send(opencat.BALANCE, read_reply=False)
                choice = input(f"\nStanding OK? Run kwkF for {walk_s:g}s then auto-rest? "
                              "[Enter/q] ").strip().lower()
                if choice != "q":
                    link.send(opencat.skill("wkF"), read_reply=False)
                    time.sleep(walk_s)
    finally:
        link.send(opencat.REST, read_reply=False)
        print("sent 'd' (rest) -- first-move check done.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="pi_pipeline.link.check_serial")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports")
    sub.add_parser("ping")
    p_send = sub.add_parser("send"); p_send.add_argument("command")
    sk = sub.add_parser("skills"); sk.add_argument("--hold", type=float, default=2.5)
    sub.add_parser("rest")
    fm = sub.add_parser("firstmove")
    fm.add_argument("--deg", type=float, default=15.0, help="degrees to nudge each joint")
    fm.add_argument("--walk-s", type=float, default=2.0, help="seconds to run wkF before auto-rest")
    args = ap.parse_args()

    if args.cmd == "ports":
        found = SerialLink.list_ports()
        for dev, desc in found:
            print(f"  {dev}  {desc}")
        print(f"  configured: {settings.serial_port} @ {settings.serial_baud}")
        if not found:
            print("  (none -- pyserial missing, or no adapters connected)")
        return

    link = _link()
    if not link.connect():
        print(f"could not open {settings.serial_port}")
        return
    try:
        if args.cmd == "ping":
            print("banner:", link.drain(1.0) or "(silent)")
            print("query :", link.send(opencat.QUERY) or "(no reply)")
        elif args.cmd == "send":
            if not opencat.is_safe(args.command):
                print(f"refusing unsafe command {args.command!r}")
                return
            print("reply:", link.send(args.command) or "(no reply)")
        elif args.cmd == "skills":
            for name, sk_ in skillcat.SKILLS.items():
                cmd = skillcat.serial_command(name)
                print(f"  {name:14} -> {cmd}")
                link.send(cmd, read_reply=False)
                time.sleep(args.hold)
            link.send(opencat.REST, read_reply=False)
        elif args.cmd == "rest":
            link.send(opencat.REST, read_reply=False)
            print("sent 'd' (rest)")
        elif args.cmd == "firstmove":
            _firstmove(link, deg=args.deg, walk_s=args.walk_s)
    finally:
        link.close()


if __name__ == "__main__":
    main()
