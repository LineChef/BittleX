"""Servo thermal guard -- a CONSERVATIVE, log-first safety net against burning
out a P1S under sustained load. See docs/research/servo-thermal.md.

The P1S has no temperature or current feedback, so heat is *estimated* from the
commanded joint motion (an I2t-style accumulator). Every constant below is a
PLACEHOLDER tuned to be gentle -- it should essentially never fire during normal
walking. Retune once we have real bench data:
  docs/research/servo-thermal.md  ->  "Retuning checklist"

Two tiers, deliberately not aggressive:
  WARN     -- G2 says "I'm getting kinda tired and need to rest for a bit."
              Keeps walking. This is the primary signal: it tells the operator
              the servos are warming and it's time to take a break.
  COOLDOWN -- near the estimated danger line, or a generous continuous-run
              backstop: G2 rests automatically for a short period, then resumes.

A dormant stall detector (set_feedback / large sustained tracking error) is
wired but inert until real servo angle feedback is available.
"""
from __future__ import annotations


from dataclasses import dataclass, field

import numpy as np

# URDF / policy joint order: [FL-sh, FL-kn, FR-sh, FR-kn, BR-sh, BR-kn, BL-sh, BL-kn]
_SHOULDER = np.array([1, 0, 1, 0, 1, 0, 1, 0], dtype=float)   # shoulders carry gravity load

# --- PLACEHOLDER constants -- gentle on purpose; retune with hardware ----------
# (docs/research/servo-thermal.md "Retuning checklist")
_STAND_DEG = np.array([35.0, -35.0, 35.0, -35.0, 35.0, -35.0, 35.0, -35.0])  # ~wkF mean, refine from wkf_ref
_K_VEL      = 0.010     # weight on |joint speed| (deg/s) in the effort proxy
_K_DEV      = 0.004     # weight on |deg from neutral stand| (gravity-held torque)
_GRAV_BOOST = 1.6       # extra weight on shoulder joints vs knees
_K_GEN      = 4.0e-3    # Joule-heating gain: H += K_GEN * tau_hat**2 * dt.
                        # Calibrated (placeholder) so gentle flat walking sits near
                        # zero, a sustained *hard* session (held offset + swing,
                        # ~= a long slope / rough traverse / pushing) reaches WARN
                        # in ~4-5 min, and only the duty-cycle backstop forces a
                        # rest on a genuinely long hard run. Retune with bench data.
_K_DISS     = 0.010     # cooling toward ambient: H -= K_DISS * (H - H_AMB) * dt  (~100 s time const)
_H_AMB      = 0.0       # ambient heat baseline (unitless; 0 with K_DISS pulling toward it)
_H_TRIP     = 60.0      # estimated danger line (unitless). Deliberately high -- a
                        # normal sustained walk should sit well under this.
_WARN_FRAC     = 0.45   # WARN at 45% of trip -- "definitely before" the danger zone
_COOLDOWN_FRAC = 0.85   # auto-rest at 85% of trip
_REARM_FRAC    = 0.30   # re-allow a WARN announcement once H falls back under 30%
_MAX_CONTINUOUS_S = 480.0   # generous backstop: 8 min of continuous locomotion ...
_COOLDOWN_S       = 20.0    # ... then a 20 s rest. Not a nag; a floor.
# NB: _MAX_CONTINUOUS_S is NOT a thermal estimate -- it is a blind "take a
# break" floor in case the heat estimator is miscalibrated. CANDIDATE FOR
# REMOVAL: once the bench test calibrates the estimator, evaluate raising this
# a lot or dropping it entirely (set to 0 to disable). See
# docs/research/servo-thermal.md "Retuning checklist".
# Dormant stall detector (needs real servo-angle feedback). Petoi-style
# per-joint reactive cutback: a joint that isn't tracking gets its command
# pulled toward neutral first (SOFT_JOINT); only a stall that won't settle
# escalates to the whole-robot lay-down (COOLDOWN).
_STALL_ERR_DEG   = 18.0    # commanded vs actual angle error ...
_STALL_SOFT_S    = 0.4     # ... this long -> soft-clamp that joint toward neutral
_STALL_HOLD_S    = 1.5     # ... this long (didn't settle) -> full lay-down
_SOFT_JOINT_SCALE = 0.35   # how far toward neutral a soft-clamped joint's cmd is pulled
# -----------------------------------------------------------------------------

WARN_PHRASE     = "I'm getting kinda tired and need to rest for a bit."
COOLDOWN_PHRASE = "I really need to rest and cool down now."


@dataclass
class GuardSnapshot:
    state: str                 # "ok" | "warn" | "soft" | "cooldown"
    H: np.ndarray              # per-joint heat estimate
    hottest_j: int
    hottest_frac: float        # hottest H / trip
    duty_s: float              # seconds of continuous locomotion since last rest
    soft_mask: np.ndarray = field(default_factory=lambda: np.zeros(8, bool))
    tripped_reason: str = ""


class ThermalGuard:
    def __init__(self, enabled: bool = True, aggressiveness: float = 1.0,
                 on_announce=None):
        """on_announce(phrase:str) -- wire to TTS if available; else print/log.
        aggressiveness scales the WARN/COOLDOWN thresholds DOWN (>1 = earlier,
        <1 = later). 1.0 = the placeholder tuning above."""
        self.enabled = enabled
        self.on_announce = on_announce or (lambda p: None)
        a = max(0.1, float(aggressiveness))
        self._warn_H = _H_TRIP * _WARN_FRAC / a
        self._cool_H = _H_TRIP * _COOLDOWN_FRAC / a
        self._rearm_H = _H_TRIP * _REARM_FRAC / a
        self.reset()

    def reset(self):
        self._H = np.zeros(8)
        self._prev_deg = None
        self._warn_armed = True
        self._duty_s = 0.0                   # accumulated locomotion time (from dt, not wall-clock)
        self._fb_err_since = np.zeros(8)     # dormant stall detector
        self._last_state = "ok"

    # -- optional: feed real servo angle feedback when hardware provides it -----
    def set_feedback(self, commanded_deg, actual_deg, dt: float):
        if actual_deg is None:
            return
        err = np.abs(np.asarray(commanded_deg, float) - np.asarray(actual_deg, float))
        stalled = err > _STALL_ERR_DEG
        self._fb_err_since = np.where(stalled, self._fb_err_since + dt, 0.0)

    def _soft_mask(self):
        """Joints not tracking their command for _STALL_SOFT_S -- Petoi-style:
        pull these toward neutral before escalating to a full lay-down."""
        return self._fb_err_since >= _STALL_SOFT_S

    def _stalled_joint(self):
        j = int(np.argmax(self._fb_err_since))
        return j if self._fb_err_since[j] >= _STALL_HOLD_S else -1

    def apply_soft(self, joint_deg, snap):
        """Blend soft-masked joints toward the neutral stand pose. No-op if
        nothing is soft-clamped (the normal case)."""
        if not snap.soft_mask.any():
            return joint_deg
        deg = np.asarray(joint_deg, dtype=float)
        pulled = deg + (_STAND_DEG - deg) * (1.0 - _SOFT_JOINT_SCALE)
        return np.where(snap.soft_mask, pulled, deg)

    # -- main update: call once per control tick with the commanded joint deg ---
    def update(self, joint_deg, dt: float) -> GuardSnapshot:
        deg = np.asarray(joint_deg, dtype=float)
        if not self.enabled:
            return GuardSnapshot("ok", self._H, 0, 0.0, 0.0)

        vel = np.zeros(8) if self._prev_deg is None else np.abs(deg - self._prev_deg) / max(dt, 1e-3)
        self._prev_deg = deg
        dev = np.abs(deg - _STAND_DEG)
        grav_w = 1.0 + (_GRAV_BOOST - 1.0) * _SHOULDER
        tau_hat = (_K_VEL * vel + _K_DEV * dev) * grav_w

        self._H += _K_GEN * tau_hat ** 2 * dt
        self._H -= _K_DISS * (self._H - _H_AMB) * dt
        np.clip(self._H, 0.0, None, out=self._H)

        self._duty_s += dt
        hj = int(np.argmax(self._H))
        hf = float(self._H[hj] / _H_TRIP)
        duty = self._duty_s

        soft_mask = self._soft_mask()
        state, reason = "ok", ""
        if self._H[hj] >= self._cool_H:
            state, reason = "cooldown", f"joint {hj} heat estimate {hf:.0%} of danger line"
        elif _MAX_CONTINUOUS_S > 0 and duty >= _MAX_CONTINUOUS_S:
            state, reason = "cooldown", f"{duty:.0f}s continuous locomotion (backstop)"
        elif self._stalled_joint() >= 0:
            j = self._stalled_joint()
            state, reason = "cooldown", f"joint {j} not tracking command for {_STALL_HOLD_S:.1f}s (possible stall)"
        elif soft_mask.any():
            state, reason = "soft", f"joints {np.where(soft_mask)[0].tolist()} eased toward neutral (not tracking)"
        elif self._H[hj] >= self._warn_H and self._warn_armed:
            state = "warn"

        if state == "warn" and self._last_state not in ("warn", "soft", "cooldown"):
            self._warn_armed = False
            self.on_announce(WARN_PHRASE)
        elif state == "cooldown" and self._last_state != "cooldown":
            self.on_announce(COOLDOWN_PHRASE)
        elif state == "ok" and self._H[hj] < self._rearm_H:
            self._warn_armed = True

        self._last_state = state
        return GuardSnapshot(state, self._H.copy(), hj, hf, duty, soft_mask, reason)

    def note_rest(self, seconds: float):
        """Call after an actual REST so the model cools and the duty timer resets."""
        self._H -= _K_DISS * (self._H - _H_AMB) * seconds
        np.clip(self._H, 0.0, None, out=self._H)
        self._duty_s = 0.0
        self._fb_err_since[:] = 0.0
        self._warn_armed = True

    @property
    def cooldown_seconds(self) -> float:
        return _COOLDOWN_S

    def is_cool(self) -> bool:
        """True once every joint's heat estimate is back below the WARN line --
        the resume condition after a danger-zone lay-down."""
        return float(self._H.max()) < self._warn_H
