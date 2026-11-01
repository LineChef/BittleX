"""Hardware test of the 3-point turn (user, 2026-11-01): back up while turning one way, then walk forward turning the OPPOSITE way.

  python -m pi_pipeline.behavior.three_point --test [--side left|right] [--back-s 1.2] [--forward-s 1.5]     (g2turn3)

On the Pi with the voice service stopped, G2 on his feet on the floor, hands near, a clear foot behind him and room to turn. It reads the pack, stands him up if he is lying, then
does the two halves one after the other and reports, from the IMU heading, how far each turned him and which way (+ = right) and, with the pack voltage, nothing else: it moves
nothing it was not asked to. Use the numbers to check that `kbkL`/`kbkR` turn the body the way the 3-point turn assumes (back-left turns him left), then set
ball_chase.WALL_THREE_POINT / SEARCH_THREE_POINT.
"""
from __future__ import annotations

import math
import time


def _yaw_deg(link, wait_s: float = 1.2) -> float | None:
    """The newest IMU heading in degrees (gyro print on for a moment); None if the board streams nothing."""
    from ..gait.imu_parse import parse_imu_line
    link.send("gP", read_reply=False, settle=0.0)
    time.sleep(wait_s)
    yaw = None
    for line in link.poll_imu():
        r = parse_imu_line(line)
        if r is not None:
            yaw = math.degrees(r[2])
    link.send("gp", read_reply=False, settle=0.0)
    return yaw


def _swing(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return (b - a + 180.0) % 360.0 - 180.0


def run_test(robot, link, side: str, back_s: float, forward_s: float, say=print, yaw=_yaw_deg) -> dict:
    """Back-turn then forward-turn toward `side`; returns {"back": deg, "forward": deg, "total": deg, "state": "ok"|"fell"} (headings from the IMU, None where unreadable)."""
    from . import ball_chase as chase
    sign = 1 if side == "right" else -1
    y0 = yaw(link)
    back_side = "left" if side == "right" else "right"                           # the back-up turns the other way; the forward half turns toward `side`, where he is going
    state = robot._skill(chase.THREE_POINT_BACK_TOKEN[back_side], back_s)
    y1 = yaw(link)
    out = {"state": state, "back": _swing(y0, y1), "forward": None, "total": None}
    say(f"backing up while turning {back_side} ({chase.THREE_POINT_BACK_TOKEN[back_side]}, {back_s:.1f} s): heading changed {out['back'] if out['back'] is None else format(out['back'], '+.0f')} deg ({'right' if sign > 0 else 'left'} is {'+' if sign > 0 else '-'})")
    if state == "fell":
        return out
    fwd = "kwkR" if side == "right" else "kwkL"
    state = robot._skill(fwd, forward_s)
    y2 = yaw(link)
    out.update(state=state, forward=_swing(y1, y2), total=_swing(y0, y2))
    say(f"forward while turning {side} ({fwd}, {forward_s:.1f} s): heading changed {out['forward'] if out['forward'] is None else format(out['forward'], '+.0f')} deg; the whole turn {out['total'] if out['total'] is None else format(out['total'], '+.0f')} deg")
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Test the 3-point turn on G2.")
    ap.add_argument("--test", action="store_true", required=True)
    ap.add_argument("--side", choices=("left", "right"), default="left")
    ap.add_argument("--back-s", type=float, default=1.2)
    ap.add_argument("--forward-s", type=float, default=1.5)
    args = ap.parse_args()
    from ..link.serial_link import SerialLink
    from ..power import battery
    from . import ball_chase as chase
    link = SerialLink("/dev/serial0")
    link.connect()
    ok, pct, volts = battery.motion_gate(link)
    print("battery:", f"{pct}% ({volts:.2f} V)" if pct is not None else "UNREADABLE", "-> ok" if ok else "-> NOT OK: stopping")
    if not ok:
        return
    chase._stand_if_lying(link)
    robot = chase.SerialRobot(link)
    try:
        run_test(robot, link, args.side, args.back_s, args.forward_s)
    except KeyboardInterrupt:
        print("ended")
    finally:
        link.send("kbalance", read_reply=False, settle=0.0)
        print("no rest command sent: left as he is")


if __name__ == "__main__":
    main()
