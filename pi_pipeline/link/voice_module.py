"""Set the BiBoard's onboard voice module to English (it falls back to Chinese or Korean after some power cycles): XAc (enable), XAb, XAa (English), one connection, 2.5 s apart.

    python -m pi_pipeline.link.voice_module english      (g2english stops the voice service around it, then starts it again)

`g2english` used to run one `check_serial send` process per command while the voice service held the port, and printed success whatever came back (2026-11-01: every reply was a left-over
"g"). Here one connection sends the three commands with the voice service stopped, drains the board's answer after each, and prints it: the module answers `X` when it took the command.
Never sends Xa or XAd (they silently break its voice commands).
"""
from __future__ import annotations

import sys
import time

SEQUENCE = ("XAc", "XAb", "XAa")
GAP_S = 2.5


def set_english(ser, say=print, sleep=time.sleep, gap_s: float = GAP_S) -> dict:
    """Send the sequence on an open serial port; returns {command: reply}. A command whose reply holds no `X` is reported, not hidden."""
    sleep(1.5)
    out = {}
    for tok in SEQUENCE:
        ser.reset_input_buffer()
        ser.write((tok + "\n").encode("ascii"))
        ser.flush()
        sleep(gap_s)
        reply = ser.read(ser.in_waiting or 1).decode("ascii", "ignore").replace("\r", " ").replace("\n", " ").strip()
        out[tok] = reply
        say(f"{tok}: " + (reply or "no reply") + ("" if "X" in reply else "   <- no X from the module"))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["english"]:
        print("usage: python -m pi_pipeline.link.voice_module english")
        return 2
    from .serial_link import SerialLink
    link = SerialLink("/dev/serial0")
    link.connect()
    ser = link._ser
    time.sleep(2.0)                                                       # right after connecting the board is still answering the link's own start-up commands
    heard = ""
    for _ in range(3):
        ser.reset_input_buffer()
        ser.write(b"P\n")
        ser.flush()
        time.sleep(2.0)
        heard = ser.read(ser.in_waiting or 1).decode("ascii", "ignore")
        if "Voltage" in heard:
            break
    if "Voltage" not in heard:                                           # a board that answers nothing cannot take the commands: say that, not "no X"
        print("the BiBoard is NOT answering a pack read after 3 tries: is it switched on, and is the Pi-to-BiBoard plug seated? Nothing was sent to the voice module.")
        return 3
    print(f"the board answers (pack {heard.split('Voltage:')[1].split('V')[0].strip()} V); sending the three commands, 2.5 s apart")
    got = set_english(ser)
    ok = "X" in got.get("XAa", "")
    print("English set: the module answered X to XAa" if "X" in got.get("XAa", "") else "NOT confirmed: the module did not answer X to XAa; say a board command (\"play sound\") to check, or run it again")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
