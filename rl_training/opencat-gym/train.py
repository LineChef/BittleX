import argparse
import os
from datetime import datetime

import gymnasium as gym
import numpy as np

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, CallbackList, CheckpointCallback
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv
from opencat_gym_env import OpenCatGymEnv

# Create OpenCatGym environment from class and check if structure is correct
#env = OpenCatGymEnv()
#check_env(env)


def linear_schedule(initial_value):
    """Linearly decay from initial_value at the start of training to 0 at the
    end. SB3 calls this with progress_remaining going from 1.0 -> 0.0.
    Added to prevent large, destabilizing updates late in training once the
    policy has converged and its action noise (std) has shrunk -- a fixed
    learning rate the whole run was a likely contributor to the recurring
    late-training collapses seen in v1 and v4.
    """
    def schedule(progress_remaining):
        return progress_remaining * initial_value
    return schedule


class RampSync(BaseCallback):
    """Tells every env the run's total step count before each rollout, so the penalty / DR ramps
    (opencat_gym_env RAMP_MODE "total") follow the whole run, not one env's share of it.
    `offset` is added to the count: a continuation passes RAMP_TOTAL_STEPS so it starts at full strength."""
    def __init__(self, offset=0.0):
        super().__init__()
        self.offset = float(offset)

    def _on_training_start(self):
        self._on_rollout_start()

    def _on_rollout_start(self):
        self.training_env.env_method("set_ramp_steps", self.offset + self.num_timesteps)

    def _on_rollout_end(self):
        try:
            lv = np.array(self.training_env.get_attr("_level"), dtype=float)
            cats = self.training_env.get_attr("_levels")               # one dict per env: {category: level}
            if lv.size:
                self.logger.record("curriculum/level_mean", float(lv.mean()))
                per = {c: float(np.mean([d[c] for d in cats])) for c in cats[0]}
                scs = self.training_env.get_attr("_cat_score")
                sc = {c: float(np.nanmean([d[c] for d in scs])) if not all(np.isnan(d[c]) for d in scs) else float("nan") for c in scs[0]}
                for c, v in per.items():
                    self.logger.record(f"curriculum/{c}", v)
                print(f"[level] steps {self.offset + self.num_timesteps:.0f}  mean level {lv.mean():.2f} (min {lv.min():.2f}, max {lv.max():.2f})  by category (level, last window score): "
                      + "  ".join(f"{c} {v:.2f} ({sc[c]:.2f})" for c, v in per.items()), flush=True)
        except Exception:
            pass

    def _on_step(self):
        return True


class CapsSync(BaseCallback):
    """The top-threshold caps (opencat_gym_env CAP_*; docs/rl/passability-audit.md) live in `trained/<tag>_caps.json` and are pushed to every env at the start of each rollout, so they can be
    raised or lowered WHILE the run trains (caps_report.py says when). At the start the file is created from the run's launch settings if it does not exist. Each change logs a `[caps]` line."""
    def __init__(self, tag):
        super().__init__()
        self.path = f"trained/{tag}_caps.json"
        self._mtime = None

    def _on_training_start(self):
        import json
        import opencat_gym_env as E
        if not os.path.exists(self.path):
            with open(self.path, "w") as f:
                json.dump(E.current_caps(), f, indent=1)
        self._push()

    def _on_rollout_start(self):
        try:
            if os.path.getmtime(self.path) != self._mtime:
                self._push()
        except OSError:
            pass

    def _push(self):
        import json
        import opencat_gym_env as E
        try:
            self._mtime = os.path.getmtime(self.path)
            caps = json.load(open(self.path))
        except (OSError, ValueError):
            return
        self.training_env.env_method("set_caps", caps)
        E.apply_caps(caps)                       # the probe env lives in this process
        print(f"[caps] steps {self.num_timesteps}  {caps}", flush=True)

    def _on_step(self):
        return True


class Curriculum(BaseCallback):
    """Difficulty curriculum driven by a DETERMINISTIC probe (opencat_gym_env LEVEL_EXTERNAL). Every `every` training steps the current policy is run, without
    exploration noise, for `episodes` episodes on each hazard category at its current level (the others at 0; random training commands); the category's mean episode
    score (survived x fraction of commanded distance covered) is compared with LEVEL_UP_SCORE / LEVEL_DOWN_SCORE: LEVEL_PROMOTE_WINDOWS consecutive good probes raise the
    category by LEVEL_STEP_C, one bad probe lowers it. The new levels are pushed to every training env. `start` is the level every category starts at."""
    def __init__(self, every=98304, episodes=6, start=0.0, ramp_offset=0.0, verbose=1):
        super().__init__(verbose)
        self.every, self.episodes = int(every), int(episodes)
        self.ramp_offset = float(ramp_offset)
        import opencat_gym_env as E
        self.E = E
        self.levels = {c: float(start) for c in E.CATS}
        self.streak = {c: 0 for c in E.CATS}
        self.last = {c: float("nan") for c in E.CATS}
        self.raw = {c: float("nan") for c in E.CATS}
        self.base = float("nan")
        self._push_ref = 0.55
        self.env = None
        self._next = self.every

    def _on_training_start(self):
        self.E.GUI_MODE = False
        self.E.CATEGORY_OVERRIDE = {}
        self.env = self.E.OpenCatGymEnv()
        self.training_env.env_method("set_category_levels", self.levels)

    def _probe(self, cat):
        """Mean episode score (survived x fraction of commanded distance) of the deterministic policy with `cat` at its level and every other category at 0.
        cat=None: the clean-floor baseline (all categories 0). The probe env gets the SAME generic-randomization ramp as the training envs.
        2026-10-08 review fixes: the category's hazard is present in EVERY probe episode (E.CATEGORY_FORCE; before, a ledge probe had a ledge in about one episode in four),
        every episode walks FORWARD (E.probe_command; stand and backward commands never reach a hazard, all of which sit ahead of the robot), and episode k uses the same
        seed and command for the clean floor and every category (env.reset now honours the seed), so the relative score compares like with like."""
        import pybullet as p
        self.E.CATEGORY_OVERRIDE = {cat if cat else "terrain": self.levels[cat] if cat else 0.0}
        self.E.CATEGORY_FORCE = bool(cat)
        self.env.set_ramp_steps(self.ramp_offset + self.num_timesteps)
        scores, signs = [], []
        for k in range(self.episodes):
            seed = int(self.num_timesteps) % 100000 + k
            self.env.set_command(fwd=self.E.probe_command(seed), yaw=0.0)
            self.env._push_curr, self.env._ep_outcomes = self._push_ref, []      # the shove size the training envs are at now, held fixed so every probe set meets the same shoves
            obs, _ = self.env.reset(seed=seed)
            signs.append(getattr(self.env, "_len_sign", 0.0))
            peak = 0.0
            while True:
                act, _ = self.model.predict(obs, deterministic=True)
                obs, _r, te, tr, _i = self.env.step(act)
                rr, pp, _y = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(self.env.robot_id)[1])
                peak = max(peak, abs(rr), abs(pp))
                if te or tr:
                    break
            scores.append(self.env._episode_score() if peak <= 1.3 else 0.0)
        self.E.CATEGORY_OVERRIDE = {}
        self.E.CATEGORY_FORCE = False
        self.env._forced_cmd = None
        if cat == "length":                              # the length level is only earned if BOTH push directions pass: the lower of the left and right means (the probe alternates the sign)
            sides = [np.mean([s for s, g in zip(scores, signs) if g == sign]) for sign in (-1.0, 1.0) if any(g == sign for g in signs)]
            return float(min(sides)) if sides else float(np.mean(scores))
        return float(np.mean(scores))

    def _on_step(self):
        return True

    def _on_rollout_end(self):
        if self.num_timesteps < self._next:
            return
        self._next += self.every
        E = self.E
        rng_state = np.random.get_state()                # the probes seed numpy's global generator (reset(seed=...)); give the trainer (minibatch shuffling) its own stream back afterwards
        try:
            self._probe_round(E)
        finally:
            np.random.set_state(rng_state)

    def _probe_round(self, E):
        try:
            self._push_ref = float(np.mean(self.training_env.get_attr("_push_curr")))
        except Exception:  # noqa: BLE001
            self._push_ref = 0.55
        base = self._probe(None)                        # what this policy scores on a clean floor under the same randomization: hazards are judged relative to it
        self.base = base
        cap = min(E.LEVEL_MAX, (self.ramp_offset + self.num_timesteps) / E.RAMP_TOTAL_STEPS) if E.LEVEL_CAP_BY_TIME else E.LEVEL_MAX
        rel = {}
        for c in E.CATS:
            raw = self._probe(c)
            rel[c] = min(1.0, raw / max(base, 0.30))      # RELATIVE score: a slow walker, or one limited by the randomization, is not penalized for it
            self.last[c], self.raw[c] = rel[c], raw
        from curriculum import update_levels
        update_levels(self.levels, self.streak, rel, base, cap, E.LEVEL_UP_SCORE, E.LEVEL_DOWN_SCORE, E.LEVEL_STEP_C, E.LEVEL_PROMOTE_WINDOWS,
                      E.LEVEL_MIN_BASELINE, E.LEVEL_COLLAPSE_BASELINE, top=E.LEVEL_MAX)
        self.training_env.env_method("set_category_levels", self.levels)
        print(f"[probe] steps {self.num_timesteps:.0f}  clean-floor score {self.base:.2f} (cap {cap:.2f}); relative score by category (raw) -> new level: "
              + "  ".join(f"{c} {self.last[c]:.2f} ({self.raw[c]:.2f}) -> {self.levels[c]:.2f}" for c in E.CATS), flush=True)


class BoundaryCheckpoint(BaseCallback):
    """Save trained/checkpoints/<tag>_<N>_steps.zip each time the run crosses a multiple N of `every` total steps (named by the boundary, so 3M / 5M / 10M checkpoints
    exist whatever the env count; SB3's CheckpointCallback names them by the step it lands on, which with 6 envs is never exactly 3,000,000)."""
    def __init__(self, every, prefix, offset=0):
        super().__init__()
        self.every, self.prefix, self.offset = int(every), prefix, int(offset)
        self._next = self.every

    def _on_step(self):
        if self.num_timesteps >= self._next:
            os.makedirs("trained/checkpoints", exist_ok=True)
            self.model.save(f"trained/checkpoints/{self.prefix}_{self._next}_steps")
            while self._next <= self.num_timesteps:
                self._next += self.every
        return True


class LeanInfo(gym.Wrapper):
    """Send the trainer only what it uses from each step's info (2026-10-08 speed pass): the frontier outcome keys. Monitor's episode stats and the VecEnv's
    terminal keys are added outside this wrapper; the episode recorder sits inside it and still sees the full info."""
    KEEP = ("fr", "fr_anchor", "episode")

    def step(self, action):
        o, r, te, tr, info = self.env.step(action)
        return o, r, te, tr, {k: info[k] for k in self.KEEP if k in info}


class FrontierCurriculum(BaseCallback):
    """The per-hazard frontier curriculum (opencat_gym_env FRONTIER; docs/plan-detail/handoff-2026-10-08.md 12.5). Reads every finished episode's outcome from the
    training envs (anchors: hazard-free; focus: one hazard at a known size bin), keeps the last WINDOW outcomes per bin, and pushes new sampling weights every rollout.
      relative success of a bin = its success / max(anchor success, 0.30)
      frontier F = the highest bin, counting up from 0, whose bins all have >= MIN_N outcomes and relative success >= PASS (no bin below it clearly failing)
      +1 bin per update at most; no advance while anchor success < LEVEL_MIN_BASELINE; one bin down below LEVEL_COLLAPSE_BASELINE; F <= FR_BINS x steps / RAMP_TOTAL_STEPS
      weights: 15% retention over 0..F-2, 20% on F-1, 35% on F, 20% on F+1, 10% on F+2; a bin past F with a full window and relative success < BLOCK is blocked:
      2% floor and nothing past it (the automatic ceiling)."""
    WINDOW, MIN_N, PASS, BLOCK, FLOOR = 300, 30, 0.5, 0.05, 0.02

    def __init__(self, tag, ramp_offset=0.0, log_every=196608):
        super().__init__()
        from collections import deque
        import opencat_gym_env as E
        self.E, self.tag, self.ramp_offset, self.log_every = E, tag, float(ramp_offset), int(log_every)
        self.K = E.FR_BINS
        self.hist = {h: [deque(maxlen=self.WINDOW) for _ in range(self.K)] for h in E.FR_HAZARDS}
        self.anchor = deque(maxlen=400)
        self.F = {h: 0 for h in E.FR_HAZARDS}
        self.blocked = {h: None for h in E.FR_HAZARDS}
        # G2E_FRONTIER_FLOOR="sidehill:5,climb:4,descent:4": a minimum frontier bin per hazard (2026-10-09). V3 passed 10 deg side-hills, 12 deg climbs and 10.8 deg descents, so those
        # sizes are known to be passable; the frontier had stalled at 2-3 deg side-hills because success on them fell under half of a hazard-free walk. Capped by the pace.
        self.floor = {}
        for part in filter(None, os.environ.get("G2E_FRONTIER_FLOOR", "").split(",")):
            k, _, v = part.partition(":")
            if k in self.F and v.strip().isdigit():
                self.floor[k] = min(int(v), self.K - 1)
        self._next_log = 0                 # the first update logs at once, then every log_every steps

    def frontier_sum(self):
        return float(sum(self.F.values()))

    def _on_training_start(self):
        self._push()

    def _on_step(self):
        for info, done in zip(self.locals.get("infos", []), self.locals.get("dones", [])):
            if not done:
                continue
            if "fr_anchor" in info:
                self.anchor.append(float(info["fr_anchor"]))
            if "fr" in info:
                hi, b, ok = info["fr"]
                self.hist[self.E.FR_HAZARDS[int(hi)]][int(b)].append(float(ok))
        return True

    def _rel(self, h, b, a):
        d = self.hist[h][b]
        return (float(np.mean(d)) / max(a, 0.30), len(d)) if d else (float("nan"), 0)

    def _update(self):
        a = float(np.mean(self.anchor)) if len(self.anchor) >= 30 else None
        steps = self.ramp_offset + self.num_timesteps
        tcap = int(self.K * min(1.0, steps / self.E.RAMP_TOTAL_STEPS))
        for h in self.E.FR_HAZARDS:
            ref = a if a is not None else 0.9
            f = 0
            for b in range(self.K):
                rel, n = self._rel(h, b, ref)
                if n >= self.MIN_N and rel >= self.PASS:
                    f = b
                elif n >= self.MIN_N and rel < 0.35:
                    break                                    # a clearly failing bin stops the climb
                elif n < self.MIN_N and b > self.F[h]:
                    break                                    # not enough evidence yet past the current frontier
            old = self.F[h]
            new = min(f, old + 1, max(0, tcap))
            if a is not None and a < self.E.LEVEL_MIN_BASELINE:
                new = min(new, old)
            if a is not None and a < self.E.LEVEL_COLLAPSE_BASELINE:
                new = max(0, old - 1)
            new = max(new, min(self.floor.get(h, 0), max(0, tcap)))           # never below the hazard's floor (when the pace allows it)
            self.F[h] = new
            self.blocked[h] = None
            for b in range(new + 1, self.K):
                rel, n = self._rel(h, b, ref)
                if n >= self.WINDOW and rel < self.BLOCK:
                    self.blocked[h] = b
                    break

    def weights(self, h):
        F, K = self.F[h], self.K
        w = np.zeros(K)
        if F >= 2:
            w[:F - 1] += 0.15 / (F - 1)
        if F >= 1:
            w[F - 1] += 0.20
        w[F] += 0.35 + (0.15 if F < 2 else 0.0) + (0.20 if F < 1 else 0.0)
        for k, share in ((1, 0.20), (2, 0.10)):
            if F + k < K:
                w[F + k] += share
        blk = self.blocked[h]
        if blk is not None:
            w[blk + 1:] = 0.0
            w[blk] = 0.0
            w = w / w.sum() * (1.0 - self.FLOOR)
            w[blk] = self.FLOOR
        return (w / w.sum()).tolist()

    def _push(self):
        payload = {"w": {h: self.weights(h) for h in self.E.FR_HAZARDS}, "comfort": {h: max(0, self.F[h] - 1) for h in self.E.FR_HAZARDS}}
        self.training_env.env_method("set_frontier", payload)
        return payload

    def _on_rollout_end(self):
        self._update()
        payload = self._push()
        if self.num_timesteps >= self._next_log:
            self._next_log += self.log_every
            a = float(np.mean(self.anchor)) if self.anchor else float("nan")
            parts = []
            for h in self.E.FR_HAZARDS:
                F = self.F[h]
                lo, hi = F / self.K * self.E.FR_BOUND[h], (F + 1) / self.K * self.E.FR_BOUND[h]
                rel, n = self._rel(h, F, a if a == a else 0.9)
                parts.append(f"{h} F{F} ({lo:.3g}-{hi:.3g}) rel {rel:.2f} n {n}" + (f" BLOCKED at {self.blocked[h]}" if self.blocked[h] is not None else ""))
            print(f"[frontier] steps {self.num_timesteps}  anchor {a:.2f} (n {len(self.anchor)}) | " + " | ".join(parts), flush=True)
            try:
                import json
                state = {"steps": int(self.num_timesteps), "anchor": a, "F": self.F, "blocked": self.blocked, "weights": payload["w"],
                         "bins": {h: [[float(np.mean(d)) if d else None, len(d)] for d in self.hist[h]] for h in self.E.FR_HAZARDS},
                         "bound": self.E.FR_BOUND, "n_bins": self.K}
                json.dump(state, open(f"trained/{self.tag}_frontier.json", "w"))
            except OSError:
                pass


class RunMonitor(BaseCallback):
    """Every `every` steps (2026-10-08 training upgrade): a fixed-difficulty deterministic EVAL (paired seeds, forward commands: a clean floor plus every hazard category
    forced present at level 1.0) whose score keeps trained/<tag>_best_ppo.zip; HEALTH checks that stop a broken run by themselves; and, with G2E_PLATEAU_STOP, the
    plateau stop (user, 2026-10-08): from MIN_STEPS on, when the eval score has not beaten its earlier best by PLATEAU_GAIN for PLATEAU_EVALS evals AND the
    curriculum's frontier / levels have not risen over the same span, the learning rate cools down to its floor over COOL_STEPS and the run then ends."""
    def __init__(self, tag, curriculum=None, every=1_000_000, plateau=False, lr_floor=0.0):
        super().__init__()
        self.tag, self.curr, self.every, self.plateau = tag, curriculum, int(every), bool(plateau)
        self.lr_floor = float(lr_floor)
        self.MIN_STEPS = int(float(os.environ.get("G2E_PLATEAU_MIN_STEPS", "10e6")))
        self.PLATEAU_EVALS, self.PLATEAU_GAIN, self.COOL_STEPS = 3, 0.02, 1_000_000
        self._next = self.every
        self.history = []            # (steps, eval score, curriculum progress)
        self.best = -1.0
        self.bad = {"ev": 0, "clean": 0}
        self.health_stop = None
        self.cool = None             # (start step, start lr, end step)
        self.env = None

    def _progress(self):
        if self.curr is None:
            return 0.0
        if hasattr(self.curr, "frontier_sum"):
            return self.curr.frontier_sum()
        return float(sum(getattr(self.curr, "levels", {}).values()))

    def _eval(self):
        import pybullet as p
        E = __import__("opencat_gym_env")
        if self.env is None:
            E.GUI_MODE = False
            self.env = E.OpenCatGymEnv()
        rng_state = np.random.get_state()
        saved = (dict(E.CATEGORY_OVERRIDE), E.CATEGORY_FORCE)
        try:
            self.env.set_ramp_steps(1e12)
            res = {}
            for cat, n in [(None, 8)] + [(c, 6) for c in E.CATS]:
                E.CATEGORY_OVERRIDE, E.CATEGORY_FORCE = ({cat: 1.0} if cat else {"terrain": 0.0}), bool(cat)
                sc = []
                for k in range(n):
                    seed = 777000 + k
                    self.env.set_command(fwd=E.probe_command(seed), yaw=0.0)
                    self.env._push_curr, self.env._ep_outcomes = 1.0, []
                    obs, _ = self.env.reset(seed=seed)
                    peak = 0.0
                    while True:
                        act, _ = self.model.predict(obs, deterministic=True)
                        obs, _r, te, tr, _i = self.env.step(act)
                        rr, pp, _y = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(self.env.robot_id)[1])
                        peak = max(peak, abs(rr), abs(pp))
                        if te or tr:
                            break
                    sc.append(0.0 if peak > 1.3 else self.env._episode_score())
                res[cat or "clean"] = float(np.mean(sc))
        finally:
            E.CATEGORY_OVERRIDE, E.CATEGORY_FORCE = saved
            self.env._forced_cmd = None
            np.random.set_state(rng_state)
        hz = [res[c] / max(res["clean"], 0.3) for c in E.CATS]
        return 0.5 * res["clean"] + 0.5 * float(np.mean(np.minimum(1.0, hz))), res

    def _lr_now(self):
        return float(self.model.policy.optimizer.param_groups[0]["lr"])

    def _on_step(self):
        if self.cool is not None:
            start, lr0, end = self.cool
            return self.num_timesteps < end
        return self.health_stop is None

    def _on_rollout_end(self):
        if self.num_timesteps < self._next or self.cool is not None:
            return
        self._next += self.every
        lg = getattr(self.model.logger, "name_to_value", {}) or {}
        ev, loss = lg.get("train/explained_variance"), lg.get("train/loss")
        score, res = self._eval()
        prog = self._progress()
        self.history.append((int(self.num_timesteps), score, prog))
        flags = []
        if loss is not None and not np.isfinite(loss):
            self.health_stop = "loss is not finite"
        if ev is not None and self.num_timesteps >= 2_000_000:
            self.bad["ev"] = self.bad["ev"] + 1 if ev < 0.2 else 0
            if ev < 0.5:
                flags.append(f"explained variance {ev:.2f} < 0.5")
            if self.bad["ev"] >= 2:
                self.health_stop = f"explained variance below 0.2 twice in a row ({ev:.2f})"
        if self.num_timesteps >= 3_000_000:
            self.bad["clean"] = self.bad["clean"] + 1 if res["clean"] < 0.35 else 0
            if self.bad["clean"] >= 2:
                self.health_stop = f"clean-floor eval below 0.35 twice in a row ({res['clean']:.2f})"
        cf = lg.get("train/clip_fraction")
        if cf is not None and cf > 0.3:
            flags.append(f"clip fraction {cf:.2f} > 0.3")
        if score > self.best:
            self.best = score
            self.model.save(f"trained/{self.tag}_best_ppo")
            flags.append("new best -> trained/%s_best_ppo.zip" % self.tag)
        print(f"[health] steps {self.num_timesteps}  eval {score:.3f} (clean {res['clean']:.2f}; " + " ".join(f"{k} {v:.2f}" for k, v in res.items() if k != "clean")
              + f")  curriculum {prog:.1f}  ev {ev if ev is None else round(ev, 2)}  " + ("; ".join(flags) if flags else "ok")
              + (f"  STOP: {self.health_stop}" if self.health_stop else ""), flush=True)
        if self.plateau and self.health_stop is None and self.num_timesteps >= self.MIN_STEPS and len(self.history) > self.PLATEAU_EVALS:
            recent, before = self.history[-self.PLATEAU_EVALS:], self.history[:-self.PLATEAU_EVALS]
            best_before = max(h[1] for h in before)
            if max(h[1] for h in recent) < best_before + self.PLATEAU_GAIN and recent[-1][2] <= before[-1][2]:
                lr0 = self._lr_now()
                end = self.num_timesteps + self.COOL_STEPS
                self.cool = (self.num_timesteps, lr0, end)
                floor = lr0 * self.lr_floor if self.lr_floor > 0 else lr0 * 0.1
                start = self.num_timesteps
                total = self.model._total_timesteps

                def cooled(progress_remaining, _start=start, _end=end, _lr0=lr0, _floor=floor, _total=total):
                    t = _total * (1.0 - progress_remaining)            # SB3's progress -> steps (the run's own counter)
                    f = min(1.0, max(0.0, (t - _start) / (_end - _start)))
                    return _lr0 + (_floor - _lr0) * f
                self.model.lr_schedule = cooled
                print(f"[plateau] steps {self.num_timesteps}: eval best {max(h[1] for h in recent):.3f} vs {best_before:.3f} before, curriculum not rising -> "
                      f"learning-rate cool-down {lr0:.2e} -> {floor:.2e} over {self.COOL_STEPS:,} steps, then the run ends", flush=True)


if __name__ == "__main__":
    # --tag names this run everywhere: checkpoints land in
    # trained/checkpoints/<tag>_<steps>_steps.zip and the final model in
    # trained/<tag>_ppo.zip. TensorBoard logging is disabled (tensorboard_log=None
    # below) -- not needed; use evaluate_policy.py / g2watch on checkpoints instead.
    # Pass the reward-iteration label, e.g.  python train.py --tag v7
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag",
                        default="run_" + datetime.now().strftime("%Y%m%d_%H%M%S"),
                        help="label for this run's checkpoint/model filenames")
    parser.add_argument("--steps", type=float, default=2e6,
                        help="total env steps to train (default 2e6)")
    parser.add_argument("--from", dest="from_ckpt", default=None,
                        help="finetune from this checkpoint (e.g. trained/auto_gait_final_ppo) "
                             "instead of training a fresh policy")
    parser.add_argument("--finetune-lr", type=float, default=3e-5,
                        help="CONSTANT LR for --from finetuning (default 3e-5). The old "
                             "linear_schedule(3e-4) restart diverged a converged policy every "
                             "time: approx_kl 70-400, clip_fraction ~0.99 (run20m from-scratch "
                             "ran at kl ~0.01). Finetuning needs a gentle nudge, not a kick.")
    parser.add_argument("--finetune-target-kl", type=float, default=0.05,
                        help="SB3 aborts an update once approx_kl exceeds this (finetune only) -- "
                             "a hard backstop against the divergence above")
    parser.add_argument("--mirror-loss", type=float, default=float(os.environ.get("G2E_MIRROR_LOSS", "0") or 0),
                        help="V3 lever R1: weight of the left/right mirror-symmetry loss (mirror.py MirrorPPO); 0 = plain PPO. "
                             "Env default G2E_MIRROR_LOSS. Value-loss weight: G2E_MIRROR_VALUE_LOSS (default 0.1)")
    parser.add_argument("--re-ramp", action="store_true",
                        help="with --from: ramp penalties / domain randomization up from zero again "
                             "(default: a continuation starts at full strength)")
    args = parser.parse_args()

    # PPO update threads (2026-10-06): on the M1 Pro the default 8 threads made the update 14.4 s per
    # rollout vs 9.6 s at 4 (686 -> 862 steps/s overall, same math). G2E_TORCH_THREADS overrides.
    import torch
    torch.set_num_threads(int(os.environ.get("G2E_TORCH_THREADS", "4")))

    # Number of parallel environments. 2026-10-08: 6 on the M1 Pro (6 performance + 2 efficiency cores: the synchronous vec env waits for its slowest env, so 6 envs
    # collected 2,284 steps/s and 8 only 2,076). Every rollout stays 16,384 steps.
    parallel_env = int(os.environ.get("G2E_N_ENVS", "8"))
    n_steps = 16384 // parallel_env
    _wrappers = []
    if int(os.environ.get("G2E_RECORD_EVERY", "0") or 0) > 0:        # record real training episodes so they can be watched exactly (watch_training.py); off by default
        from episode_recorder import RecordingWrapper
        os.environ.setdefault("G2E_RECORD_DIR", f"trained/{args.tag}_episodes")
        _wrappers.append(RecordingWrapper)
    if os.environ.get("G2E_LEAN_INFO", "0") not in ("0", ""):          # send the trainer only the info it uses (outermost, so the recorder still sees all of it)
        _wrappers.append(LeanInfo)

    def _wrap(e):
        for w in _wrappers:
            e = w(e)
        return e
    env = make_vec_env(OpenCatGymEnv,
                       n_envs=parallel_env,
                       vec_env_cls=SubprocVecEnv, wrapper_class=_wrap if _wrappers else None)
    # Optimizer bundle (lever opt_bundle, 2026-10-08): reward normalization for the critic (the policy never sees rewards, nothing changes on the Pi; obs untouched)
    if os.environ.get("G2E_NORM_REWARD", "0") not in ("0", ""):
        from stable_baselines3.common.vec_env import VecNormalize
        env = VecNormalize(env, norm_obs=False, norm_reward=True, gamma=0.99)

    # Change architecture of neural network to two hidden layers of size 256
    custom_arch = dict(net_arch=[256, 256])
    if os.environ.get("G2E_LOG_STD_INIT", "") != "":                   # opt_bundle: smaller starting exploration noise (-1 = std 0.37 instead of 1.0)
        custom_arch["log_std_init"] = float(os.environ["G2E_LOG_STD_INIT"])
    import opencat_gym_env as _E
    policy_cls = "MlpPolicy"
    if _E.PRIV_OBS:                                                     # lever privileged_critic: the actor never sees the privileged values (priv_policy.py)
        from priv_policy import PrivCriticPolicy
        policy_cls = PrivCriticPolicy
        custom_arch["priv_dim"] = _E.PRIV_DIM
    ppo_batch, ppo_epochs = int(os.environ.get("G2E_PPO_BATCH", "64")), int(os.environ.get("G2E_PPO_EPOCHS", "10"))   # lever big_batch: 4096 x 5
    lr_floor = float(os.environ.get("G2E_LR_FLOOR", "0") or 0)        # opt_bundle: the linear decay ends at this fraction of 3e-4 instead of 0

    lr_scale = float(os.environ.get("G2E_LR_SCALE", "1") or 1)          # lever lr_half: the whole schedule (start and floor) scaled, 0.5 = start at 1.5e-4

    def lr_schedule(progress_remaining, _f=lr_floor):
        return 3e-4 * lr_scale * (_f + (1.0 - _f) * progress_remaining)

    # Save a checkpoint every 200K total env steps, so an interruption only costs progress back to the last checkpoint. Named by the 200k boundary crossed.
    checkpoint_callback = BoundaryCheckpoint(200_000, args.tag)
    if args.mirror_loss > 0:
        from mirror import MirrorPPO
        PPOCls = MirrorPPO
        print(f"mirror-symmetry loss ON: policy weight {args.mirror_loss}, value weight "
              f"{float(os.environ.get('G2E_MIRROR_VALUE_LOSS', '0.1'))}", flush=True)
    else:
        PPOCls = PPO
    ramp_offset = max(_E.RAMP_TOTAL_STEPS, _E.RAMP_PENALTY_STEPS) if (args.from_ckpt and not args.re_ramp) else 0.0
    cbs = [RampSync(ramp_offset), CapsSync(args.tag), checkpoint_callback]
    curriculum = None
    if _E.FRONTIER:                                                     # the per-hazard frontier replaces the probe-driven category levels
        curriculum = FrontierCurriculum(args.tag, ramp_offset=ramp_offset)
    elif _E.LEVEL_EXTERNAL and _E.ADAPTIVE_LEVEL and _E.CATEGORY_LEVELS:
        curriculum = Curriculum(every=int(os.environ.get("G2E_PROBE_EVERY", "98304")), episodes=int(os.environ.get("G2E_PROBE_EPISODES", "6")),
                                start=_E.LEVEL_FIXED if _E.LEVEL_FIXED >= 0 else _E.LEVEL_START, ramp_offset=ramp_offset)
    if curriculum is not None:
        cbs.append(curriculum)
    monitor = None
    if os.environ.get("G2E_RUN_MONITOR", "0") not in ("0", ""):        # eval + best checkpoint + health checks (+ plateau stop with G2E_PLATEAU_STOP)
        monitor = RunMonitor(args.tag, curriculum, every=int(float(os.environ.get("G2E_MONITOR_EVERY", "1e6"))),
                             plateau=os.environ.get("G2E_PLATEAU_STOP", "0") not in ("0", ""), lr_floor=lr_floor)
        cbs.append(monitor)
    checkpoint_callback = CallbackList(cbs)

    if args.from_ckpt:
        # Finetune: load the policy and nudge it with a low CONSTANT LR plus a
        # target_kl early-stop. The previous linear_schedule(3e-4) restart on a
        # converged policy diverged every time (approx_kl 70-400, clip_fraction
        # ~0.99); see --finetune-lr help.
        print(f"finetuning from {args.from_ckpt}  "
              f"(lr={args.finetune_lr}, target_kl={args.finetune_target_kl})")
        model = PPOCls.load(args.from_ckpt, env=env,
                         n_steps=n_steps,
                         learning_rate=args.finetune_lr,
                         target_kl=args.finetune_target_kl,
                         tensorboard_log=None)
        if args.mirror_loss > 0:
            model.mirror_w, model.mirror_wv = args.mirror_loss, float(os.environ.get("G2E_MIRROR_VALUE_LOSS", "0.1"))
        model.learn(args.steps, callback=checkpoint_callback,
                    reset_num_timesteps=True)
    else:
        model = PPOCls(policy_cls, env, seed=int(os.environ.get("G2E_SEED", "42")),
                    policy_kwargs=custom_arch,
                    n_steps=n_steps, batch_size=ppo_batch, n_epochs=ppo_epochs,
                    learning_rate=lr_schedule,
                    verbose=1,
                    tensorboard_log=None)
        if args.mirror_loss > 0:
            model.mirror_w, model.mirror_wv = args.mirror_loss, float(os.environ.get("G2E_MIRROR_VALUE_LOSS", "0.1"))
        model.learn(args.steps, callback=checkpoint_callback)

    if monitor is not None and monitor.health_stop:
        model.save(f"trained/{args.tag}_health_stop_ppo")
        print(f"[health] run STOPPED: {monitor.health_stop}; saved trained/{args.tag}_health_stop_ppo.zip (no final model, so the queue runner halts)", flush=True)
        raise SystemExit(3)
    model.save(f"trained/{args.tag}_ppo")

    # Load model to continue previous training
    #model = PPO.load("trained/opencat_gym_esp32_trained_controller", 
    #                   env, policy_kwargs=custom_policy_kwargs, 
    #                   n_steps=int(2048*8/parallel_env), verbose=1, 
    #                   tensorboard_log="trained/tensorboard_logs/").learn(2e6)
    #model.save("trained/opencat_gym_esp32_trained_controller_2")


