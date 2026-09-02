# Other people's learned-gait work on the Petoi Bittle

Research pass (2026-09-01) — every RL / learned-gait project I could find that
targets the Bittle specifically, and what's applicable to making **our** gait
more reliable. Sources linked inline.

## The projects

| project | sim / algo | on real Bittle hardware? |
|---|---|---|
| **[`ger01d/opencat-gym`](https://github.com/ger01d/opencat-gym)** (our vendored base) | PyBullet + SB3, **SAC → PPO** (switched for training stability), MLP [256,256] | via `opencat-gym-sim2real` |
| **[`ger01d/opencat-gym-sim2real`](https://github.com/ger01d/opencat-gym-sim2real)** | modified BiBoard firmware takes joint commands over serial, inference on a connected PC | **"still highly experimental"** — no success metrics, no video, no gap analysis published |
| **[`Amaranth819/Bittle_Symmetry_RL`](https://github.com/Amaranth819/Bittle_Symmetry_RL)** | Isaac Gym, PPO, **symmetry-guided reward**; 45 obs / 9 act, 200 Hz | open-loop Bluetooth "hardware test module" only |
| **[One Policy to Run Them All / URMA](https://arxiv.org/html/2409.06366)** (Bohlinger et al, CoRL 2024) | multi-robot PPO (RL-X), Bittle is 1 of 16 training robots | Bittle **trained but not deployed**; real tests were A1 / Honey Badger / Silver Badger |
| **[Tiny RL / Decision Transformers](https://arxiv.org/pdf/2402.13201)** (2402.13201) | Isaac Gym, offline **Decision Transformer** from IK-generated expert data, 4-bit quantized | **future work** — not done |
| **[`gravesreid/mujoco_mpc_bittle`](https://github.com/gravesreid/mujoco_mpc_bittle)** | MuJoCo MPC (MJPC) — model-predictive, not RL | open-loop gaits played on hardware |
| **[Symmetry-Guided RL](https://arxiv.org/html/2403.10723v3)** (2403.10723, same author as Bittle_Symmetry_RL) | Isaac Gym, PPO, MLP [512,256,128] | validated on **Unitree Go2**, not Bittle — but the framework is what `Bittle_Symmetry_RL` ports |

### Meta-finding

**Nobody has published a robustly-working, closed-loop RL gait on real Bittle
hardware.** Every project either stops at "experimental," leaves hardware as
future work, or runs open-loop. The platform is hard for the same reasons we've
hit: ~0.29 N·m servos with backlash + zero-point drift, IMU-only sensing, a
~50 Hz control ceiling on the BiBoard. Our planned **RL-vs-scripted head-to-head
on the real robot will be genuinely novel data**, and we should not expect a
recipe that erases the platform ceiling (our ~25% reactive-recovery plateau is
consistent with everyone else hitting the same wall).

---

## What's applicable to us — ranked

### 1. Symmetry rewards — the most-cited reliability lever for Bittle

`Bittle_Symmetry_RL`'s entire thesis, and its ICRA'25 paper shows the ablations:
**morphological symmetry → +45 % energy efficiency and better gait consistency;
time-reversal symmetry → directional robustness** — *"without the need for
extensive reward tuning."* Two concrete terms we don't have:

- **Phase-gated foot term (temporal symmetry).** Tie it to the gait clock:
  penalise ground-reaction force on a foot during its *swing* phase, and penalise
  foot *sliding speed* during its *stance* phase.
  `R = −Σ_i [ I_swing(φ_i)·(1−e^{−k1‖F_i‖}) + I_stance(φ_i)·(1−e^{−k2‖v_i‖}) ]`.
  `Bittle_Symmetry_RL` weights this 0.25 + 0.25. We have `FAC_SLIP` and
  `FAC_CLEARANCE` but nothing that enforces a *clean, consistent cycle* against
  the phase signal.
- **Morphological (left/right) symmetry.** Mirror the observation, mirror the
  action, penalise the difference between the policy's response and its mirrored
  response. `Bittle_Symmetry_RL` weights this 0.15; URMA weights its symmetry
  term 0.5. Our `FAC_GAIT_SYMMETRY` rewards a *diagonal-trot correlation*, which
  is related but weaker — it doesn't enforce mirrored joint trajectories.

**Effort:** medium. PyBullet already gives us foot contacts; we need a
left↔right (and diagonal) joint index map for the mirror term. **Highest-value
single change.**

### 2. Match the training control rate to the real BiBoard (~50 Hz)

`ger01d`'s headline sim-to-real lesson was that **NyBoard → BiBoard "significantly
reduced latencies"** and that's what made transfer viable — latency/rate matters
more than almost anything on this platform. `URMA` and `Bittle_Symmetry_RL` both
run their PD loop at 50 Hz (URMA) / high rate. **Ours is `CONTROL_HZ = 80`, but
the real BiBoard is ~48–50 Hz** — the real robot would run our policy ~1.6×
slower than it was trained for. Either drop `CONTROL_HZ` to ~50 to match, or
randomise it. **Effort:** trivial. This is a free systematic-gap fix.

### 3. Domain randomization we're missing — actuator delay + joint offset

URMA's DR list (explicitly *"necessary to ensure policies transfer"*, resampled
~2×/episode): trunk mass+inertia, CoM displacement, foot sizes, joint
torque/velocity limits, joint damping, rotor inertia, joint stiffness, joint
friction, joint control ranges, ground friction, gravity, contact
stiffness/damping, PD gains, **action-scaling factor, motor strength, joint
offsets, actuator delays**, initial state, obs noise, **obs dropout**, velocity
perturbation.

We have friction / mass / gyro-noise / push / terrain / joint-angle-history
noise. The two most impactful for **cheap-servo transfer** that we lack:
- **Actuator delay** — a randomized 1–3 control-step lag between commanded and
  applied joint target. Cheap servos + serial + a 50 Hz loop = real latency.
- **Joint calibration offset** — a small fixed per-joint zero-point error each
  episode (±a few degrees). Bittle servos are never perfectly zeroed.
Also cheap to add: **PD-gain / motor-strength randomization** and **observation
dropout** (randomly zero an obs).
**Effort:** low–medium.

### 4. A body-height target reward

URMA weights **walking-height at 30.0** — by far its biggest penalty coefficient.
A crouched / collapsed / "walking on its knees" gait is *the* classic RL failure
mode on Bittle (Petoi's own blog cites *"jumping on their knees"*). We have
`FAC_UPRIGHT` (tilt) but no term that holds the body at a target *height*. Add
`−FAC_HEIGHT · (h − H_TARGET)²`. **Effort:** low.

### 5. Widen the residual authority

Residual-on-a-nominal-pose is the consensus action space:
- URMA: `q_target = q_nominal + σ_a·a`, **σ_a = 0.6 rad** for Bittle
- `Bittle_Symmetry_RL`: position targets, **0.5 action scale**
- Ours: `wkF(phase) + a·deg2rad(RESIDUAL_SCALE_DEG)`, **RESIDUAL_SCALE_DEG = 11°
  ≈ 0.19 rad** — 3× tighter than both.

Our residual may not have the authority to actually correct a stumble. Test
`RESIDUAL_SCALE_DEG` at ~20–25° (≈ 0.35–0.44 rad). **Effort:** trivial (one
constant).

### 6. Explicit joint-limit-proximity penalty

URMA weights its **joint-limits penalty at 10.0** (strong). We clip the action
but never penalise the *target* approaching the URDF limits, so the policy can
learn to ride the clip. Add a soft penalty as any joint nears its range.
**Effort:** low.

---

## What we're already doing right (don't churn these)

- **Residual-on-`wkF`** action space — matches URMA / `Bittle_Symmetry_RL`.
- **PPO over SAC** — exactly the switch `ger01d` made for stability.
- **Long penalty ramp relative to run length** — URMA ramps penalties 0→full
  over 40M steps; we learned the same lesson the hard way (the v1–v5 late
  collapse, fixed with `PENALTY_STEPS` + LR decay).
- **Adaptive push curriculum** — more sophisticated than anything in these
  projects; keep it.
- **IMU-only-ish observation** (commanded joint history + quat + ang-vel +
  phase) — the DT paper validates IMU-only is enough for a natural Bittle gait
  in sim; we're hardware-honest and not missing a sensor.
- **`net_arch=[256,256]`** — `ger01d`'s size; URMA's core is ~430k params, a
  similar order. Fine.

## Suggested order of experiments

1. **Control rate → 50 Hz** (free, closes a real gap) — do this first, re-baseline.
2. **Body-height target reward** (kills the crouch failure mode).
3. **Morphological + phase-gated symmetry rewards** (the big one; do it as its
   own round so its effect is isolated).
4. **Actuator-delay + joint-offset DR** (sim-to-real insurance; low cost to gait
   quality if the ranges are modest).
5. **`RESIDUAL_SCALE_DEG` 11 → ~22** (quick A/B).
6. Joint-limit-proximity penalty (polish).

---

## Empirical note — `cov_r1_slope` is a cadence-specific heading corrector (2026-09-01)

Ran `cov_r1_slope` on flat ground with only the gait clock scaled (`_phase`
advance ×N, no retraining), 20 episodes/rate:

| clock | fwd m/s | lat drift (signed) | yaw | falls |
|---|---|---|---|---|
| 1× | 0.091 | +0.004 m | −0.8° | 0/20 |
| 2× | 0.162 | +0.041 m | +8.5° | 0/20 |
| 3× | 0.220 | +0.071 m | +11.3° | 0/20 |
| 4× | 0.227 | +0.069 m | +8.4° | 0/20 |

- **Never falls**, even at 4× cadence — the gait is robust for *staying
  upright* off-cadence.
- Drift is a **consistent directional bias** (always +y / left, same-sign yaw)
  across all seeds — a baked-in `wkF` left/right asymmetry, not wobble.
- The heading correction **works only at the training cadence**: 0.004 m drift
  at 1×, 10× worse (0.041 m) the moment you go to 2×, then ~flat. The learned
  residual is not a general "walk straight" skill, it's a corrector tuned to the
  exact training stride frequency.
- Speed saturates: 2× clock → 1.78× speed, 4× clock → only 2.5× (foot slip
  dominates past ~3×).

**Implications:** (a) direct evidence for the mirror-symmetry reward and
gait-frequency randomization above; (b) the sim-80 Hz vs real-~50 Hz cadence
mismatch (0.625×) is a milder version of this same off-cadence condition —
expect some heading drift on hardware from the rate mismatch alone, fixed by
training at 50 Hz.
