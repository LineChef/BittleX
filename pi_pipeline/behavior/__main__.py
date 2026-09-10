"""`python -m pi_pipeline.behavior` -- run the behaviour runtime against mocks
and print the effect stream. A visible smoke test of the Phase 10 loop with no
hardware: idle descent -> sit -> rest -> (long quiet) sleep, then a scripted
`wake_word` rouses it.

    python -m pi_pipeline.behavior              # ~40 simulated seconds
    python -m pi_pipeline.behavior --secs 120
"""
from __future__ import annotations

import argparse
import logging

from ..personality.traits import BehaviorParams
from .bindings import MockBindings
from .driver import BehaviorDriver
from .runtime import BehaviorRuntime
from .sleep_mode import SleepModeConfig


def main() -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.behavior")
    ap.add_argument("--secs", type=float, default=40.0, help="simulated seconds")
    ap.add_argument("--hz", type=float, default=5.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    t = [0.0]
    dt = 1.0 / args.hz
    driver = BehaviorDriver(
        BehaviorParams(idle_secs_before_explore=1e9, idle_sit_secs=4, idle_rest_secs=6),
        clock=lambda: t[0],
        sleep_cfg=SleepModeConfig(sleep_after_resting_s=8.0, settle_timeout_s=2.0),
    )
    mb = MockBindings()
    rt = BehaviorRuntime(driver, mb, hz=0, clock=lambda: t[0])

    wake_at = args.secs * 0.75
    woke = False
    for _ in range(int(args.secs / dt)):
        t[0] += dt
        if not woke and t[0] >= wake_at:
            rt.post(wake_word=True)
            woke = True
        before = len(mb.calls)
        tick = rt.tick()
        new = [f"{n}{a}" for n, a, _ in mb.calls[before:]]
        if new:
            print(f"t={t[0]:6.1f}s  {tick.mode.value:<8} {tick.posture.value:<7} "
                  f"sleep={tick.sleep_state.value:<7} mood={tick.mood.value:<8} "
                  f"-> {'  '.join(new)}")

    print(f"\n{len(mb.calls)} sink calls total")


if __name__ == "__main__":
    main()
