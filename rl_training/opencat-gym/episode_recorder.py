"""Record real training episodes so they can be watched later EXACTLY as they happened (watch_training.py).

A training episode is fully determined by four things: the env settings (the G2E_* variables), the trainer-set state at its start (the total step count that drives the ramps,
and the difficulty levels), the random generator's state at its start, and the actions the policy took. `RecordingWrapper` saves those for a fraction of the episodes of
every env (default one in `G2E_RECORD_EVERY`, off when 0), plus the outcome, so the viewer can rebuild the same terrain, obstacles, shoves and slope and feed the same
actions. It draws its own sampling decisions from Python's `random`, never `np.random`, so recording does not change the stream the env uses, and nothing it does can
raise into training. Files: `trained/<tag>_episodes/ep_<time>_<pid>_<n>.npz` (the newest `G2E_RECORD_KEEP`, default 80, are kept).
"""
from __future__ import annotations

import glob
import json
import os
import random
import time

import gymnasium as gym
import numpy as np


def _env_vars() -> dict:
    return {k: v for k, v in os.environ.items() if k.startswith("G2E_")}


class RecordingWrapper(gym.Wrapper):
    def __init__(self, env, directory: str | None = None, every: int | None = None, keep: int | None = None):
        super().__init__(env)
        self._every = int(every if every is not None else os.environ.get("G2E_RECORD_EVERY", "0") or 0)
        self._dir = directory or os.environ.get("G2E_RECORD_DIR", "trained/episodes")
        self._keep = int(keep if keep is not None else os.environ.get("G2E_RECORD_KEEP", "80"))
        self._pyrng = random.Random()
        self._rec = None
        self._n = 0

    def reset(self, **kw):
        self._rec = None
        try:
            if self._every > 0 and self._pyrng.random() < 1.0 / self._every:
                u = self.env.unwrapped
                if kw.get("seed") is not None:                 # the env seeds numpy itself at reset (SB3 passes the run seed on the first reset): record the state it will start from
                    np.random.seed(int(kw["seed"]) % (2 ** 32))
                import opencat_gym_env as _E
                # 2026-10-08 review fix: the shove multiplier (adaptive per env) and the live caps (trained/<tag>_caps.json) also shape the episode; without them a replay
                # differed whenever a shove landed or a cap had been moved
                self._rec = {"rng": np.random.get_state(), "ramp_steps": getattr(u, "_train_total_steps", None),
                             "levels": dict(getattr(u, "_levels", {})), "len_ep": int(getattr(u, "_len_ep", 0)),
                             "forced_cmd": getattr(u, "_forced_cmd", None), "push_curr": float(getattr(u, "_push_curr", 0.55)),
                             "caps": _E.current_caps(), "actions": [], "ramp_events": [], "t0": time.time(),
                             "frontier": {"w": {h: [float(x) for x in w] for h, w in getattr(u, "_fr_w", {}).items()},
                                          "comfort": {h: int(c) for h, c in getattr(u, "_fr_comfort", {}).items()}}}
        except Exception:  # noqa: BLE001 -- recording must never break training
            self._rec = None
        return self.env.reset(**kw)

    def set_ramp_steps(self, total_steps):
        """The trainer's ramp update (train.py RampSync, every rollout) can land MID-episode and moves the penalty scale from that step on: record when, so a replay
        applies it at the same step (2026-10-08: 4 of 80 recorded control episodes differed in their final reward without this)."""
        self.env.unwrapped.set_ramp_steps(total_steps)
        if self._rec is not None:
            try:
                self._rec["ramp_events"].append([len(self._rec["actions"]), float(total_steps)])
            except Exception:  # noqa: BLE001
                pass

    def step(self, action):
        out = self.env.step(action)
        if self._rec is not None:
            try:
                self._rec["actions"].append(np.array(action, dtype=np.float32))
                terminated, truncated = out[2], out[3]
                if terminated or truncated:
                    self._save(out)
            except Exception:  # noqa: BLE001
                self._rec = None
        return out

    def _save(self, out) -> None:
        rec, self._rec = self._rec, None
        u = self.env.unwrapped
        info = out[4] if len(out) > 4 and isinstance(out[4], dict) else {}
        os.makedirs(self._dir, exist_ok=True)
        self._n += 1
        path = os.path.join(self._dir, f"ep_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}_{self._n}.npz")
        _, key, pos, has_gauss, cached = rec["rng"]            # np.random.get_state() = (name, 624-word key, position, has_gauss, cached_gaussian)
        meta = {"env": _env_vars(), "ramp_steps": rec["ramp_steps"], "levels": rec["levels"], "len_ep": rec["len_ep"], "forced_cmd": rec["forced_cmd"],
                "push_curr": rec.get("push_curr"), "caps": rec.get("caps"), "frontier": rec.get("frontier"), "ramp_events": rec.get("ramp_events", []),
                "steps": len(rec["actions"]), "terminated": bool(out[2]), "truncated": bool(out[3]), "final_reward": float(out[1]),
                "focus": getattr(u, "_focus", None), "d": {c: float(getattr(u, "_d_" + c, 0.0)) for c in ("terrain", "ledge", "slope", "fault")},
                "slope_rp": [float(x) for x in getattr(u, "_slope_rp", (0.0, 0.0))], "slope_targeted": bool(getattr(u, "_slope_targeted", False)),
                "info": {k: (float(v) if isinstance(v, (int, float, np.floating)) else str(v)) for k, v in info.items() if isinstance(v, (int, float, np.floating, str, bool))},
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        np.savez_compressed(path + ".tmp.npz", actions=np.array(rec["actions"]), rng_key=key, rng_pos=np.int64(pos), rng_gauss=np.int64(has_gauss),
                            rng_cached=np.float64(cached), meta=np.array(json.dumps(meta, default=str)))
        os.replace(path + ".tmp.npz", path)
        files = sorted(glob.glob(os.path.join(self._dir, "ep_*.npz")), key=os.path.getmtime)
        for old in files[:-self._keep] if self._keep > 0 else []:
            try:
                os.remove(old)
            except OSError:
                pass


def load_episode(path: str) -> dict:
    z = np.load(path, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    rng = ("MT19937", z["rng_key"], int(z["rng_pos"]), int(z["rng_gauss"]), float(z["rng_cached"]))
    return {"meta": meta, "actions": z["actions"], "rng": rng, "path": path}
