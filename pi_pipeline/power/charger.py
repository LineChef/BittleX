"""Whether the Pi is on its charger, as the user says (2026-11-04). The PiSugar S has no readout, so the Pi cannot tell by itself: `python -m pi_pipeline.power plugged` records it,
`... unplugged` clears it. While it is recorded, Wi-Fi power-save stays OFF (power.set_wifi_power_save refuses to turn it on): with power-save on, the Pi's radio only listens now and then
and the Mac can lose it (sleep mode turns power-save on after 5 minutes at rest). On the battery nothing changes: sleep mode still saves power.

    ~/.local/share/g2/on_charger        (G2_ON_CHARGER moves it)   present = on the charger; kept until `unplugged` (it survives a reboot)
"""
from __future__ import annotations

import os
import time

PATH = "~/.local/share/g2/on_charger"


def path() -> str:
    return os.path.expanduser(os.environ.get("G2_ON_CHARGER", PATH))


def is_plugged() -> bool:
    return os.path.exists(path())


def plugged_since() -> str | None:
    try:
        return open(path()).read().strip() or None
    except OSError:
        return None


def set_plugged(on: bool) -> bool:
    """Record that the Pi is (or is no longer) on the charger. Returns True when this changed anything."""
    p = path()
    if on:
        if os.path.exists(p):
            return False
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
        return True
    try:
        os.remove(p)
        return True
    except FileNotFoundError:
        return False
