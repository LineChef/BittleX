"""Exercise the vision pipeline against a mock detection feed. No hardware.

    python -m pi_pipeline.vision demo            # an object approaching dead ahead
    python -m pi_pipeline.vision demo --bearing 0.2   # ...from the left
    python -m pi_pipeline.vision serial /dev/ttyAMA1  # real feed (hardware)
    python -m pi_pipeline.vision eval /dev/cu.usbmodemXXX --label person --secs 30
        # timed measurement: detection rate / confidence / floor / flicker --
        # the numbers for the dataset-size threshold experiment. Re-run with
        # --expect-empty pointing at a clear scene for the false-fire check.
"""
from __future__ import annotations

import argparse
import logging
import time
from collections import Counter

from ..config import settings
from .avoidance import ACTION_SKILL, Avoider, AvoidanceAction
from .feed import MockDetectionFeed, SerialDetectionFeed
from .scene import summarize


def _pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def _eval(feed, label: str, secs: float, expect_empty: bool) -> None:
    label = (label or "").lower()
    floor = settings.vision_min_score or 45   # runtime score floor (VISION_MIN_SCORE)
    t0 = time.time()
    n = n_hit = flicker = 0
    confs: list[float] = []
    other: Counter = Counter()
    prev_hit = False
    last_tick = t0
    mode = "expect EMPTY" if expect_empty else f"label={label or '(any)'}"
    print(f"measuring [{mode}] -- {'Ctrl-C to stop' if secs <= 0 else f'{secs:.0f}s'}\n")
    try:
        for frame in feed.frames():
            n += 1
            best = None
            for d in frame:
                dl = d.label.lower()
                if label and dl == label:
                    best = max(best or 0.0, d.confidence * 100.0)
                elif dl != label:
                    other[d.label] += 1
            hit = best is not None or (not label and len(frame) > 0)
            if hit:
                n_hit += 1
                if best is not None:
                    confs.append(best)
            if hit != prev_hit:
                flicker += 1
            prev_hit = hit
            now = time.time()
            if now - last_tick >= 1.0:
                last_tick = now
                rate = 100 * n_hit / max(1, n)
                cm = f"conf mu{sum(confs)/len(confs):.0f} min{min(confs):.0f}" if confs else "conf --"
                print(f"  {now - t0:4.0f}s  frames {n:4d}  det {rate:3.0f}%  {cm}  "
                      f"flicker {flicker // 2}")
            if secs > 0 and now - t0 >= secs:
                break
    except KeyboardInterrupt:
        pass
    finally:
        feed.close()

    dur = time.time() - t0
    rate = n_hit / max(1, n)
    fpm = (flicker // 2) / max(1e-6, dur / 60)
    print(f"\n=== eval [{mode}]  {n} frames over {dur:.0f}s  ({n / max(dur,1e-6):.1f} fps) ===")
    if expect_empty:
        worst = max(confs) if confs else 0
        print(f"false-fire rate   {rate:.0%}   ({n_hit}/{n} frames had a box)")
        if confs:
            print(f"  worst score     {worst:.0f}")
        if other:
            print("  other labels    " + ", ".join(f"{k} x{v}" for k, v in other.most_common()))
        v = ("PASS" if rate < 0.03 and worst < floor
             else "MARGINAL" if rate < 0.10 else "FAIL")
        print(f"VERDICT: {v}")
        return
    p10 = _pct(confs, 10)
    print(f"detection rate    {rate:.0%}   ({n_hit}/{n} frames)")
    if confs:
        print(f"confidence        mean {sum(confs)/len(confs):.0f}   median {_pct(confs,50):.0f}   "
              f"p10 {p10:.0f}   min {min(confs):.0f}   max {max(confs):.0f}")
        print(f"  floor (p10)     {p10:.0f}   "
              + ("OK" if p10 >= floor
                 else f"< score floor ({floor}) -> dropouts"))
    print(f"flicker           {flicker // 2} drops  ({fpm:.1f}/min)")
    if other:
        print("other labels      " + ", ".join(f"{k} x{v}" for k, v in other.most_common()))
    v = ("PASS" if rate >= 0.80 and (p10 or 0) >= floor
         else "MARGINAL" if rate >= 0.65 and (p10 or 0) >= floor - 10
         else "FAIL")
    print(f"VERDICT: {v}   (bar: det >= 80%, conf floor >= {floor})")


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
    e = sub.add_parser("eval", help="timed detection-rate / confidence / floor measurement")
    e.add_argument("port")
    e.add_argument("--label", default=None,
                   help="class to score (default: first of VISION_LABELS)")
    e.add_argument("--secs", type=float, default=30.0, help="0 = until Ctrl-C")
    e.add_argument("--expect-empty", action="store_true",
                   help="clear scene -- measure false-fire rate instead")
    args = ap.parse_args()

    def _serial_feed(min_score):
        return SerialDetectionFeed(
            args.port, settings.vision_serial_baud,
            frame_px=settings.vision_frame_px, labels=settings.vision_labels,
            sensor_opt=settings.vision_sensor_opt, ae_bump=settings.vision_ae_bump,
            min_score=min_score,
        )

    if args.cmd == "demo":
        script = MockDetectionFeed.approaching(steps=args.steps, bearing=args.bearing)
        _run(MockDetectionFeed(script))
    elif args.cmd == "serial":
        _run(_serial_feed(settings.vision_min_score))
    elif args.cmd == "eval":
        label = args.label or (settings.vision_labels[0] if settings.vision_labels else "")
        _eval(_serial_feed(0), label, args.secs, args.expect_empty)  # min_score=0: see every score


if __name__ == "__main__":
    main()
