"""SkillSwitch -- vision decides *which motion drives the servos*: the learned
walk, or a scripted keyframe skill, with a blended handoff so the switch doesn't
lurch.

Phase E-1 of the vision-triggered-skills plan (docs/rl-runs/vision-goal-locomotion-plan.md).
The learned residual gait (`gait/residual_policy.py`) stays the base -- it is
never retrained. When a situation calls for a specific motion (step over a low
obstacle, crouch to look at near ground, hold still), this layer takes control
for a few strides, plays a scripted OpenCat keyframe skill, and hands back.

Pure logic + a keyframe interpolator. No onnxruntime, no serial, no pybullet.
The caller feeds it the RL policy's current joint output and a requested
`GaitMode`; it returns the joint targets to actually send and which source they
came from. Mirrors the CliffGuard / RecoveryFSM shape.

  CRUISE --(request STEP_OVER / INSPECT)--> BLEND_IN --> PLAYING --> BLEND_OUT --> CRUISE
  CRUISE --(request CAREFUL)--> CRUISE, but `speed_scale` < 1 (RL still drives)
  any    --(request HALT)--> BLEND_IN(halt pose) --> HOLDING  (preempts a running skill)

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
    HALT = "halt"              # scripted neutral stand, held (preempts everything)


class Source(Enum):
    RL = "rl"                  # joints came straight from the learned policy
    BLEND = "blend"            # interpolating between RL and a scripted frame
    SCRIPTED = "scripted"      # joints came from a keyframe skill


@dataclass
class SkillSwitchConfig:
    blend_in_steps: int = 4        # control ticks to lerp RL pose -> skill frame 0
    blend_out_steps: int = 4       # ticks to lerp skill last frame -> RL pose
    step_over_cycles: float = 1.0  # how many full keyframe loops a STEP_OVER plays
    play_ticks_per_cycle: int = 60  # control ticks to play one 100-frame ref cycle
    # STEP_OVER auto-releases after its cycles; INSPECT / HALT hold until the mode
    # request changes back to CRUISE / CAREFUL.
    latch_skill: bool = True       # ignore new non-HALT requests while a skill runs


@dataclass
class SkillRefs:
    """Keyframe references, shape (N, 8), RADIANS, URDF joint order -- the same
    format as reference_gait/*_ref.npy. `stand` is a single-frame neutral pose."""
    step_over: np.ndarray                       # e.g. tr_ref.npy or an authored high-step
    inspect: np.ndarray                         # e.g. cr_ref.npy (crouch)
    stand: np.ndarray = field(                  # neutral hold for HALT
        default_factory=lambda: np.zeros((1, 8)))


def _lerp(a, b, t):
    return a + (b - a) * float(np.clip(t, 0.0, 1.0))


class SkillSwitch:
    """update(mode, rl_joint_deg) -> (joint_deg, Source). Feed every control tick."""

    def __init__(self, refs: SkillRefs, cfg: SkillSwitchConfig | None = None):
        self._cfg = cfg or SkillSwitchConfig()
        self._src_refs = refs
        # keep refs in DEGREES internally to match the deployment joint interface
        self._ref = {
            GaitMode.STEP_OVER: np.rad2deg(np.asarray(refs.step_over, float)),
            GaitMode.INSPECT: np.rad2deg(np.asarray(refs.inspect, float)),
            GaitMode.HALT: np.rad2deg(np.asarray(refs.stand, float)),
        }
        self._careful = False
        self._state = "cruise"          # cruise | blend_in | playing | holding | blend_out
        self._skill: GaitMode | None = None
        self._blend_t = 0               # tick counter within a blend
        self._skill_phase = 0.0         # frames into the current ref (float)
        self._from_pose = np.zeros(8)   # pose we blended out of / into
        self._last_rl = np.zeros(8)
        self._last_reason = ""

    @property
    def source(self) -> Source:
        return {"cruise": Source.RL, "blend_in": Source.BLEND, "blend_out": Source.BLEND,
                "playing": Source.SCRIPTED, "holding": Source.SCRIPTED}[self._state]

    @property
    def active_skill(self) -> GaitMode | None:
        return self._skill

    @property
    def speed_scale(self) -> float:
        """Forward-speed multiplier the caller should apply to the RL command.
        <1 only while CAREFUL and RL is driving."""
        return 0.6 if (self._state == "cruise" and self._careful) else 1.0

    @property
    def last_reason(self) -> str:
        return self._last_reason

    def reset(self) -> None:
        self.__init__(self._src_refs, self._cfg)

    # -- ref sampling ------------------------------------------------

    def _ref_frame(self, mode: GaitMode, phase: float) -> np.ndarray:
        r = self._ref[mode]
        n = len(r)
        if n == 1:
            return r[0]
        f = phase % n
        i = int(f)
        return _lerp(r[i], r[(i + 1) % n], f - i)

    # -- tick -----------------------------------------------------

    def update(self, mode: GaitMode, rl_joint_deg) -> tuple[np.ndarray, Source]:
        c = self._cfg
        rl = np.asarray(rl_joint_deg, float)
        self._last_rl = rl
        self._careful = mode is GaitMode.CAREFUL

        want_skill = mode in (GaitMode.STEP_OVER, GaitMode.INSPECT, GaitMode.HALT)

        # ---- CRUISE / CAREFUL : RL drives ----------------------------
        if self._state == "cruise":
            if want_skill:
                return self._begin(mode, rl)
            self._say(f"{mode.value}: RL drives" + (" @0.6x" if self._careful else ""))
            return rl, Source.RL

        # ---- BLEND IN : RL pose -> skill frame 0 --------------------
        if self._state == "blend_in":
            if mode is GaitMode.HALT and self._skill is not GaitMode.HALT:
                return self._begin(GaitMode.HALT, self._blended_now())  # re-target
            self._blend_t += 1
            t = self._blend_t / max(1, c.blend_in_steps)
            target = self._ref_frame(self._skill, 0.0)
            out = _lerp(self._from_pose, target, t)
            if self._blend_t >= c.blend_in_steps:
                self._state = "playing" if self._skill is GaitMode.STEP_OVER else "holding"
                self._skill_phase = 0.0
                self._say(f"{self._skill.value}: blended in")
                return out, Source.SCRIPTED     # blend complete -> now on the skill frame
            self._say(f"{self._skill.value}: blend in {self._blend_t}/{c.blend_in_steps}")
            return out, Source.BLEND

        # ---- PLAYING : run the keyframe loop -----------------------
        if self._state == "playing":
            if mode is GaitMode.HALT:
                return self._begin(GaitMode.HALT, self._ref_frame(self._skill, self._skill_phase))
            n = len(self._ref[self._skill])
            self._skill_phase += n / max(1, c.play_ticks_per_cycle)
            done = self._skill_phase >= n * c.step_over_cycles
            if done:
                self._from_pose = self._ref_frame(self._skill, self._skill_phase)
                self._state = "blend_out"
                self._blend_t = 0
                self._say(f"{self._skill.value}: done, blending out")
                return self._from_pose, Source.SCRIPTED
            self._say(f"{self._skill.value}: playing {self._skill_phase:.0f}/{n * c.step_over_cycles:.0f}")
            return self._ref_frame(self._skill, self._skill_phase), Source.SCRIPTED

        # ---- HOLDING : INSPECT / HALT posture, until CRUISE asked ---
        if self._state == "holding":
            if mode in (GaitMode.CRUISE, GaitMode.CAREFUL):
                self._from_pose = self._ref_frame(self._skill, 0.0)
                self._state = "blend_out"
                self._blend_t = 0
                self._say(f"{self._skill.value}: released, blending out")
                return self._from_pose, Source.SCRIPTED
            if mode is GaitMode.HALT and self._skill is not GaitMode.HALT:
                return self._begin(GaitMode.HALT, self._ref_frame(self._skill, 0.0))
            if mode in (GaitMode.STEP_OVER, GaitMode.INSPECT) and mode is not self._skill \
                    and not c.latch_skill:
                return self._begin(mode, self._ref_frame(self._skill, 0.0))
            self._say(f"{self._skill.value}: holding")
            return self._ref_frame(self._skill, 0.0), Source.SCRIPTED

        # ---- BLEND OUT : skill pose -> RL pose ---------------------
        self._blend_t += 1
        t = self._blend_t / max(1, c.blend_out_steps)
        out = _lerp(self._from_pose, rl, t)
        if self._blend_t >= c.blend_out_steps:
            self._state = "cruise"
            self._skill = None
            self._say("blended out -> RL drives")
            return out, Source.RL              # blend complete -> back on the RL pose
        self._say(f"blend out {self._blend_t}/{c.blend_out_steps}")
        return out, Source.BLEND

    # -- helpers --------------------------------------------------

    def _begin(self, skill: GaitMode, from_pose) -> tuple[np.ndarray, Source]:
        self._skill = skill
        self._from_pose = np.asarray(from_pose, float)
        self._state = "blend_in"
        self._blend_t = 0
        self._skill_phase = 0.0
        self._say(f"{skill.value}: begin (blend in)")
        return self._from_pose, Source.BLEND

    def _blended_now(self) -> np.ndarray:
        t = self._blend_t / max(1, self._cfg.blend_in_steps)
        return _lerp(self._from_pose, self._ref_frame(self._skill, 0.0), t)

    def _say(self, reason: str) -> None:
        self._last_reason = reason
        log.debug("skillswitch: %s", reason)
