"""SkillSwitch -- vision decides *which motion drives the servos*: the learned
walk, or a scripted keyframe skill, with a smooth handoff so the switch doesn't
lurch.

Phase E-1 of the vision-triggered-skills plan (docs/rl-runs/vision-goal-locomotion-plan.md).
The learned residual gait (`gait/residual_policy.py`) stays the base -- it is
never retrained. When a situation calls for a specific motion (step over a low
obstacle, crouch to look at near ground, hold still), this layer takes control
for a few strides, plays a scripted OpenCat keyframe skill, and hands back.

Two things make the handoff smooth:
  * PHASE-GATED START -- when a skill is requested, wait (up to a cap) for a
    stance / double-support moment in the wkF cycle before starting the blend,
    so a foot isn't mid-swing when control changes. Pass `gait_phase` (0..1) to
    update(); omit it to start immediately (HALT always starts immediately).
  * VIA-STANCE BLEND -- interpolate RL pose -> neutral stance -> skill frame 0
    (and the reverse on the way out), so both endpoints of every blend are a
    stable four-foot stance, not a mid-cycle keyframe.

Pure logic + a keyframe interpolator. No onnxruntime, no serial, no pybullet.

  CRUISE --req skill--> PENDING --(stance phase)--> BLEND_IN --> PLAYING/HOLDING
         --> BLEND_OUT --> CRUISE
  CRUISE --req CAREFUL--> CRUISE, `speed_scale` 0.6 (RL still drives)
  any    --req HALT--> BLEND_IN(stance) --> HOLDING  (immediate, preempts a skill)

Scripted-skill trade-off: keyframes are open-loop -- no balance feedback mid-skill
-- so a shove during a STEP_OVER can drop it. If that proves too fragile on
hardware, that one skill becomes a learned module (the adapter probe path).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

log = logging.getLogger("g2.gait.skillswitch")


class GaitMode(Enum):
    CRUISE = "cruise"          # the learned walk drives
    CAREFUL = "careful"        # learned walk drives, but at reduced speed
    STEP_OVER = "step_over"    # scripted high-step / trot keyframes, then hand back
    INSPECT = "inspect"        # scripted crouch, held, so the mast pitches down
    HALT = "halt"              # scripted neutral stance, held (preempts everything)


class Source(Enum):
    RL = "rl"                  # joints came straight from the learned policy
    BLEND = "blend"            # interpolating RL <-> stance <-> a scripted frame
    SCRIPTED = "scripted"      # joints came from a keyframe skill


_SKILL_MODES = (GaitMode.STEP_OVER, GaitMode.INSPECT, GaitMode.HALT)


@dataclass
class SkillSwitchConfig:
    blend_in_steps: int = 4         # control ticks: RL pose -> stance -> skill frame 0
    blend_out_steps: int = 4        # ticks: skill pose -> stance -> RL pose
    step_over_cycles: float = 1.0   # full keyframe loops a STEP_OVER plays
    play_ticks_per_cycle: int = 60  # control ticks to play one ref cycle
    latch_skill: bool = True        # ignore new non-HALT requests while a skill runs
    # phase-gated start (tune the windows against wkf_ref's real contact pattern)
    stance_phase_windows: tuple = ((0.0, 0.15), (0.5, 0.65))  # wkF phase, 0..1
    max_pending_ticks: int = 25     # start anyway after this many ticks waiting


@dataclass
class SkillRefs:
    """Keyframe references, shape (N, 8), RADIANS, URDF joint order -- the same
    format as reference_gait/*_ref.npy. `stance` is a single neutral four-foot
    pose (e.g. wkf_ref.mean(0)); it is the HALT hold AND the via-point of every
    blend."""
    step_over: np.ndarray                       # e.g. tr_ref.npy or an authored high-step
    inspect: np.ndarray                         # e.g. cr_ref.npy (crouch)
    stance: np.ndarray = field(
        default_factory=lambda: np.zeros(8))


def _lerp(a, b, t):
    return a + (b - a) * float(np.clip(t, 0.0, 1.0))


def _via(a, w, b, t):
    """a -> w over t in [0, 0.5], then w -> b over [0.5, 1]."""
    t = float(np.clip(t, 0.0, 1.0))
    return _lerp(a, w, t * 2.0) if t <= 0.5 else _lerp(w, b, (t - 0.5) * 2.0)


class SkillSwitch:
    """update(mode, rl_joint_deg, gait_phase=None) -> (joint_deg, Source).
    Call every control tick."""

    def __init__(self, refs: SkillRefs, cfg: SkillSwitchConfig | None = None):
        self._cfg = cfg or SkillSwitchConfig()
        self._src_refs = refs
        # internal units: DEGREES, to match the deployment joint interface
        self._ref = {
            GaitMode.STEP_OVER: np.rad2deg(np.atleast_2d(np.asarray(refs.step_over, float))),
            GaitMode.INSPECT: np.rad2deg(np.atleast_2d(np.asarray(refs.inspect, float))),
        }
        self._stance = np.rad2deg(np.asarray(refs.stance, float)).reshape(8)
        self._careful = False
        self._state = "cruise"    # cruise | pending | blend_in | playing | holding | blend_out
        self._skill: str | None = None
        self._pending: str | None = None
        self._pending_t = 0
        self._blend_t = 0
        self._skill_phase = 0.0
        self._from_pose = np.zeros(8)
        self._last_reason = ""

    @property
    def source(self) -> Source:
        return {"cruise": Source.RL, "pending": Source.RL,
                "blend_in": Source.BLEND, "blend_out": Source.BLEND,
                "playing": Source.SCRIPTED, "holding": Source.SCRIPTED}[self._state]

    @property
    def active_skill(self) -> str | None:
        return self._skill

    @property
    def speed_scale(self) -> float:
        """Forward-speed multiplier for the RL command. <1 only while CAREFUL and
        the RL policy is still driving (cruise or waiting for a stance window)."""
        return 0.6 if (self._state in ("cruise", "pending") and self._careful) else 1.0

    @property
    def last_reason(self) -> str:
        return self._last_reason

    def reset(self) -> None:
        self.__init__(self._src_refs, self._cfg)

    # -- ref sampling ---------------------------------------------

    def _frame(self, skill: str, phase: float) -> np.ndarray:
        r = self._ref[skill]
        n = len(r)
        if n == 1:
            return r[0]
        f = phase % n
        i = int(f)
        return _lerp(r[i], r[(i + 1) % n], f - i)

    def _skill_start_pose(self, skill: str) -> np.ndarray:
        return self._stance if skill == GaitMode.HALT else self._frame(skill, 0.0)

    def _in_stance_window(self, gait_phase: float) -> bool:
        p = float(gait_phase) % 1.0
        return any(lo <= p <= hi for lo, hi in self._cfg.stance_phase_windows)

    # -- tick ---------------------------------------------------

    def update(self, mode: GaitMode, rl_joint_deg, gait_phase=None) -> tuple[np.ndarray, Source]:
        c = self._cfg
        rl = np.asarray(rl_joint_deg, float).reshape(8)
        self._careful = mode is GaitMode.CAREFUL
        want_skill = mode in _SKILL_MODES

        # ---- CRUISE / CAREFUL -------------------------------------
        if self._state == "cruise":
            if want_skill:
                if mode == GaitMode.HALT or gait_phase is None:
                    return self._begin(mode, rl)
                self._pending, self._pending_t, self._state = mode, 0, "pending"
                self._say(f"{mode}: pending a stance window")
                return rl, Source.RL
            self._say(f"{mode}: RL drives" + (" @0.6x" if self._careful else ""))
            return rl, Source.RL

        # ---- PENDING : keep walking until a stance phase ---------
        if self._state == "pending":
            if not want_skill:
                self._state, self._pending = "cruise", None
                self._say("pending aborted -- RL drives")
                return rl, Source.RL
            if mode == GaitMode.HALT and self._pending != GaitMode.HALT:
                return self._begin(GaitMode.HALT, rl)
            self._pending_t += 1
            ready = (self._pending == GaitMode.HALT
                     or (gait_phase is not None and self._in_stance_window(gait_phase))
                     or self._pending_t >= c.max_pending_ticks)
            if ready:
                return self._begin(self._pending, rl)
            self._say(f"{self._pending}: waiting for stance ({self._pending_t}/{c.max_pending_ticks})")
            return rl, Source.RL

        # ---- BLEND IN : RL pose -> stance -> skill frame 0 -------
        if self._state == "blend_in":
            if mode == GaitMode.HALT and self._skill != GaitMode.HALT:
                return self._begin(GaitMode.HALT, self._blended_now())
            self._blend_t += 1
            t = self._blend_t / max(1, c.blend_in_steps)
            out = _via(self._from_pose, self._stance, self._skill_start_pose(self._skill), t)
            if self._blend_t >= c.blend_in_steps:
                self._state = "playing" if self._skill == GaitMode.STEP_OVER else "holding"
                self._skill_phase = 0.0
                self._say(f"{self._skill}: blended in")
                return out, Source.SCRIPTED
            self._say(f"{self._skill}: blend in {self._blend_t}/{c.blend_in_steps}")
            return out, Source.BLEND

        # ---- PLAYING : run the keyframe loop --------------------
        if self._state == "playing":
            if mode == GaitMode.HALT:
                return self._begin(GaitMode.HALT, self._frame(self._skill, self._skill_phase))
            n = len(self._ref[self._skill])
            self._skill_phase += n / max(1, c.play_ticks_per_cycle)
            if self._skill_phase >= n * c.step_over_cycles:
                self._from_pose = self._frame(self._skill, self._skill_phase)
                self._state, self._blend_t = "blend_out", 0
                self._say(f"{self._skill}: done, blending out")
                return self._from_pose, Source.SCRIPTED
            self._say(f"{self._skill}: playing {self._skill_phase:.0f}/{n * c.step_over_cycles:.0f}")
            return self._frame(self._skill, self._skill_phase), Source.SCRIPTED

        # ---- HOLDING : INSPECT / HALT pose, until released ------
        if self._state == "holding":
            if mode in (GaitMode.CRUISE, GaitMode.CAREFUL):
                self._from_pose = self._skill_start_pose(self._skill)
                self._state, self._blend_t = "blend_out", 0
                self._say(f"{self._skill}: released, blending out")
                return self._from_pose, Source.SCRIPTED
            if mode == GaitMode.HALT and self._skill != GaitMode.HALT:
                return self._begin(GaitMode.HALT, self._skill_start_pose(self._skill))
            if (mode in (GaitMode.STEP_OVER, GaitMode.INSPECT)
                    and mode != self._skill and not c.latch_skill):
                return self._begin(mode, self._skill_start_pose(self._skill))
            self._say(f"{self._skill}: holding")
            held = self._stance if self._skill == GaitMode.HALT else self._frame(self._skill, 0.0)
            return held, Source.SCRIPTED

        # ---- BLEND OUT : skill pose -> stance -> RL pose --------
        self._blend_t += 1
        t = self._blend_t / max(1, c.blend_out_steps)
        out = _via(self._from_pose, self._stance, rl, t)
        if self._blend_t >= c.blend_out_steps:
            self._state, self._skill = "cruise", None
            self._say("blended out -> RL drives")
            return out, Source.RL
        self._say(f"blend out {self._blend_t}/{c.blend_out_steps}")
        return out, Source.BLEND

    # -- helpers -----------------------------------------------

    def _begin(self, skill: str, from_pose) -> tuple[np.ndarray, Source]:
        self._skill = skill
        self._from_pose = np.asarray(from_pose, float).reshape(8)
        self._state = "blend_in"
        self._blend_t = 0
        self._skill_phase = 0.0
        self._pending, self._pending_t = None, 0
        self._say(f"{skill}: begin (blend in via stance)")
        return self._from_pose, Source.BLEND

    def _blended_now(self) -> np.ndarray:
        t = self._blend_t / max(1, self._cfg.blend_in_steps)
        return _via(self._from_pose, self._stance, self._skill_start_pose(self._skill), t)

    def _say(self, reason: str) -> None:
        self._last_reason = reason
        log.debug("skillswitch: %s", reason)
