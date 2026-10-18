"""The Phase E vision-skill pieces of the walk loop: the skill layer (scripted OpenCat keyframe skills chosen by vision), the background camera
reader, the firmware hand-off for an edge, and the feed factory. Split out of run_gait.py 2026-10-18 (no behaviour change); run_gait re-exports every name."""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, ".."), os.path.join(_HERE, "..", "..")):     # run by path like run_gait.py: siblings, `link`, the repo root
    if _p not in sys.path:
        sys.path.insert(0, _p)

import time

import numpy as np

from walk_common import _send                                 # noqa: E402

try:                                                          # Phase E vision-skill layer (optional)
    from pi_pipeline.gait.skill_layer import SkillLayer       # noqa: E402
    from pi_pipeline.gait.skill_switch import SkillRefs       # noqa: E402
    from pi_pipeline.vision.cliff_guard import CliffAction, CliffGuard, action_commands  # noqa: E402
except Exception:                                             # noqa: BLE001 -- runs blind without it
    SkillLayer = None


_REF_DIRS = (_HERE, os.path.join(_HERE, "..", "..", "rl_training", "opencat-gym",
                                 "reference_gait"))


def _load_ref(name):
    """(N,8) rad keyframe array from pi_pipeline/gait/ or the training reference_gait/."""
    for d in _REF_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return np.load(p).astype(np.float64)
    raise FileNotFoundError(f"{name} not found in {[os.path.normpath(d) for d in _REF_DIRS]}")


def build_skill_layer(*, with_cliff_guard=True):
    """Assemble the Phase E SkillLayer from the shipped keyframe references.
    step_over -> trot (tr_ref, won the item-1 A/B), inspect -> crouch, back_out ->
    walk-backward, brace -> derived from stance, stance -> wkF mean pose."""
    if SkillLayer is None:
        raise RuntimeError("skill layer deps missing (pi_pipeline.vision / .gait import failed)")
    refs = SkillRefs(
        step_over=_load_ref("tr_ref.npy"),
        inspect=_load_ref("inspect_sweep_ref.npy"),   # up-and-down camera scan (nose-up -> bow)
        back_out=_load_ref("bk_ref.npy"),
        brace=None,                                   # derived: stance + knee flex
        stance=_load_ref("wkf_ref.npy").mean(axis=0),
    )
    return SkillLayer(refs, cliff_guard=CliffGuard() if with_cliff_guard else None)


class _LatestFrame:
    """Pull `feed.frames()` in a daemon thread; expose the newest frame without
    blocking the 80 Hz loop. `latest()` returns [] once a frame is older than
    `stale_after` s (detector dropped out -> treat as 'nothing seen')."""

    def __init__(self, feed, stale_after=0.6):
        import threading
        self._feed = feed
        self._stale = float(stale_after)
        self._frame = []
        self._stamp = 0.0
        self._stop = threading.Event()
        self._look_down = False
        self._th = threading.Thread(target=self._pump, name="vision-feed", daemon=True)

    def start(self):
        self._th.start()
        return self

    def _pump(self):
        try:
            for fr in self._feed.frames():
                if self._stop.is_set():
                    break
                self._frame, self._stamp = fr, time.time()
        except Exception as e:  # noqa: BLE001 -- a dead feed must not kill the gait
            print(f"[skills] vision feed stopped: {e!r}", flush=True)

    def latest(self):
        if time.time() - self._stamp > self._stale:
            return []
        return self._frame

    def set_look_down(self, v):
        self._look_down = bool(v)

    def close(self):
        self._stop.set()
        try:
            self._feed.close()
        except Exception:  # noqa: BLE001
            pass


def _cliff_firmware_action(lk, cliff_action, turn_burst_s):
    """The gait layer can only HALT for an edge -- turning is a firmware job.
    When CliffGuard asks to turn away / back up, hand off to the OpenCat scripted
    turn gait for a short burst, then let the policy loop resume and CliffGuard
    re-evaluate the next edge read. Returns True if it drove the servos this tick
    (caller skips its normal move send). FREEZE is handled by the caller."""
    if SkillLayer is None or cliff_action is None:
        return False
    if cliff_action in (CliffAction.TURN_AWAY_LEFT, CliffAction.TURN_AWAY_RIGHT,
                        CliffAction.BACK_UP):
        for tok in action_commands(cliff_action):
            _send(lk, tok)
        time.sleep(max(0.0, turn_burst_s))
        return True
    return False


def _make_vision_feed(kind, port, baud):
    """kind: 'serial' (Grove Vision AI on its own USB port) or 'mock:approach'
    (a scripted box growing in the path, loops -- bench check without the camera)."""
    from pi_pipeline.vision.feed import MockDetectionFeed, SerialDetectionFeed
    if kind == "serial":
        labels = [s for s in os.environ.get("VISION_LABELS", "").split(",") if s]
        return SerialDetectionFeed(port, baud, labels=labels or None,
                                   min_score=int(os.environ.get("VISION_MIN_SCORE", "40")))
    if kind.startswith("mock"):
        script = MockDetectionFeed.approaching(steps=10, bearing=0.5)
        return MockDetectionFeed(script * 1000, interval=0.4)
    raise SystemExit(f"unknown --skills-feed {kind!r} (want 'serial' or 'mock')")
