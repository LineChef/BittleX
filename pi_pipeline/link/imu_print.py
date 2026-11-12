"""The board's IMU print (`gP` on, `gp` off) is shared: the stand guard, the walk loops and the turn measurement all read it, and the guard sends `gP` once at its start. A read that needs the board
quiet (the joint read `j`, which often failed while the stream ran) must therefore put the print back the way it found it. Before 2026-11-12 the pose read before every stand-up switched it off for
good, so a roam ran with no IMU frames: the fall guard, the sag check and the turn measurement saw nothing (two falls and a sag went unseen).

    with imu_print.paused(link):          # the print is off inside, and back on after if it was on before
        ...
"""
from __future__ import annotations

from contextlib import contextmanager


def is_on(link) -> bool:
    return bool(getattr(link, "imu_print_on", False))


@contextmanager
def paused(link):
    was_on = is_on(link)
    link.send("gp", read_reply=False, settle=0.0)
    try:
        yield
    finally:
        if was_on:
            try:
                link.send("gP", read_reply=False, settle=0.0)
            except Exception:  # noqa: BLE001
                pass
