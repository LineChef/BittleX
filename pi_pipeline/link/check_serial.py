"""Serial-link diagnostics for the BiBoard. Needs pyserial + a connected robot.

    python -m pi_pipeline.link.check_serial ports              # list serial ports
    python -m pi_pipeline.link.check_serial ping               # open the configured port, poke it
    python -m pi_pipeline.link.check_serial send kbalance       # send one command, print the reply
    python -m pi_pipeline.link.check_serial skills              # cycle the conversational skill set
    python -m pi_pipeline.link.check_serial rest                # send 'd' (safe state)
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="pi_pipeline.link.check_serial")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports")
    sub.add_parser("ping")
    p_send = sub.add_parser("send"); p_send.add_argument("command")
    sk = sub.add_parser("skills"); sk.add_argument("--hold", type=float, default=2.5)
    sub.add_parser("rest")
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
    finally:
        link.close()


if __name__ == "__main__":
    main()
