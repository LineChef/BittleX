# Servo thermal management — Bittle X (G2)

Research + mitigation plan for the servo "thermal cliff": the sharp, non-linear
torque collapse when a P1S servo (or its driver) crosses a current/temperature
limit under sustained load. Researched 2026-09-05.

---

## 1. What to expect on our hardware

### The P1S servo (×8 legs + 1 neck)

| Spec | Value | Source |
|---|---|---|
| Peak torque | ~3 kg·cm (~0.29 N·m) | Petoi listing / `hardware-specs.md` |
| No-load speed | ~0.07 s/60° (~14 rad/s) | Petoi listing |
| Motor | coreless DC, alloy gears, ball bearing | Petoi listing |
| Rated life | "100+ h continuous walking" | Petoi listing |
| Voltage | 8.4 V compatible (2S Li-ion, 7.4 V nominal) | Petoi |
| Protection | "electronic overheat cutback" | Petoi (no detail published) |
| Winding temp sensor | **none** | coreless micro servos don't have one |
| Datasheet | **not published** by Petoi (forum requests unanswered) | petoi.camp |

### How the "cliff" actually works here

There is **no thermistor** in a P1S. What Petoi calls "overheat cutback" is
almost certainly **firmware/driver over-*current* protection**, not a
temperature reading — confirmed indirectly by Petoi's own docs: when new gears
are too tight, "the servo protection algorithm reduces force on the joint to
avoid overcurrent and stops the joint from moving." Current, not temperature,
is the trigger.

So the failure chain on G2 is:

1. Sustained high torque demand (stance-holding, uphill, shove-catching,
   carrying the ~76 g payload) → high winding current, low RPM → worst-case
   Joule heating (I²R, no back-EMF to limit current, no airflow).
2. Winding resistance rises with temperature (~+0.4 %/°C for copper), so for
   the same voltage the current *falls* — but to hold the load the controller
   demands *more* → positive feedback.
3. The firmware's over-current threshold is effectively lower once the winding
   is hot (same torque now needs more current), so protection trips **earlier
   than the nominal stall spec** — and it trips **mid-task**, mid gait-cycle.
4. On a trip: that joint's torque is cut / it freezes. One frozen leg joint
   mid-stride ⇒ topple. Short bench tests never show this; it needs tens of
   seconds to minutes of continuous hard work.

### Permanent-damage risks (why this matters beyond a fall)

- **Coreless brush wear** accelerates sharply under continuous load — coreless
  brushes are thinner than cored. This is cumulative, not recoverable.
- **Gear-train stress**: alloy gears here (not the worst case), but sustained
  near-stall torque still fatigues them; plastic idler/output stages on some
  units act as a mechanical fuse and strip.
- **Driver IC**: sustained over-current cooks the servo's onboard H-bridge —
  "melted gears and a shorted driver IC" is the classic coreless-servo autopsy.
- **Magnet**: at extreme temps, partial demagnetisation of the rotor magnet =
  permanent torque loss even after cooling. Unlikely at our loads but the
  end-stop of the cliff.

### Battery interaction (compounds it)

The 2S pack sags 7.4 V → ~6.6 V under load and toward empty. Lower voltage →
less torque per amp → the controller pushes *more* current for the same torque
→ more heat. **A low battery behaves like a hot servo.** Runtime is ~45–60 min
of active walking (1000 mAh, 2 A typ / 5 A peak), so a single charge won't cook
a servo from cold — the risk window is *sustained hard work within* that hour
(long rough/uphill traverse, repeated stumble-catches).

### Bottom line for G2

- We have **no direct signal** of servo temperature. Feedback servos give
  joint *angle* back (slow, ~10–30 Hz), not current or temp.
- `TARGET_SPEED` 0.10 m/s (~¼ of the ~0.38 m/s envelope) and sim effective
  torque ~0.2 N·m of 0.29 peak keep the *average* joint well out of the stall
  regime. The risk is **individual joints intermittently near stall** under
  slopes / shoves / payload, integrated over a long session.
- **We have no hardware data on trip time or cooldown rate.** Getting that (one
  bench test, §4) is the single biggest unknown.

---

## 2. Mitigation plan — layered

### Layer 0 — already in place

- **`FAC_POWER` penalty** (`0.05 · Σ|τ·ω|`, ramped) — trains toward a
  low-current gait. Already thermal-adjacent work.
- **`TORQUE_CUTBACK` domain randomisation** — 40 % of training episodes weaken
  1–3 random joints by a random fraction. Trains robustness to *a* weak joint,
  but it's a **static per-episode draw**, not a joint that fades *during* the
  episode as it heats.
- **`d` (REST)** — de-energises all servos. The fundamental cooldown; already
  wired in `pi_pipeline` (`REST = "d"`, sent on every gait-loop exit).
- **Low `TARGET_SPEED`** keeps the mean well clear of stall.

### Layer 1 — sensorless estimator + indicator (no new hardware, no retraining)

**I²t thermal estimator** — the industry-standard sensorless winding-temp proxy
(maxon, Synapticon, Ingenia motion controllers all ship this). Per joint:

```
H_j += k_gen · tau_hat_j**2 · dt        # Joule heating  ∝ I²  ∝ τ²
H_j -= k_diss · (H_j - H_amb) · dt      # Newton cooling toward ambient
```

`tau_hat_j` = a torque estimate per joint. We don't have per-joint current, but
we do have: (a) commanded vs actual joint-angle error from the feedback servos
(bigger error under load ⇒ higher current), (b) the gait/policy's commanded
joint target vs the wkF reference, (c) total pack current from the board
(~2 A typ / 5 A peak). Blend into a per-joint proxy; **calibrate `k_gen`,
`k_diss` against one bench test** (§4).

**Indicator** — 3-tier per-joint state:

| State | H_j vs estimated trip | Action |
|---|---|---|
| GREEN | < 50 % | normal |
| AMBER | 50–85 % | governor throttles (Layer 2) |
| RED | > 85 % | forced cooldown (Layer 2) |

Surface it: LED pattern, the Pi status channel, and — since G2 has the voice
pipeline — a spoken heads-up ("my left-front leg is getting warm"). Always log
per-joint `H_j` so we can tune the model from real runs.

### Layer 2 — behaviour-layer duty-cycle governor (no retraining)

In `pi_pipeline/behavior/` (same pattern as explore mode):

- **AMBER on any joint** → cap commanded speed, soften gait aggressiveness,
  bias path planning away from sustained uphill.
- **RED** → force a **cooldown pose** for N seconds: a folded low-torque stance
  where the frame/elbows carry the weight, not the shoulder servos (keeps
  IMU/vision alive and resumes faster than full `d`). Fall back to `d` if it
  can't reach the pose.
- Cheap, reversible, ships without touching the policy.

### Layer 3 — thermal-aware residual policy (needs training; the literature blueprint)

**Almost exactly our architecture already.** See
[arXiv:2605.27046](https://arxiv.org/abs/2605.27046), *"Learning to Balance
Motor Thermal Safety and Quadrupedal Locomotion Performance with Residual
Policy"* (Unitree A1):

- **Two-stage**: frozen nominal policy (= our `run20m_ppo`), then a **residual
  policy** on top that receives **per-motor temperatures** in its observation
  and a **thermal-safety reward**. Nominal policy is untouched.
- **Thermal reward**:
  `R_th = ω_th · Σ_i Ṫ_i · exp(−min(σ_th·(T_max − T_i), 0))`
  with `ω_th = −1000`, `σ_th = 0.35`, `T_max = 60 °C`. ≈ zero when cool;
  exponential ramp above ~50 °C. Penalises **heating rate**, weighted by
  proximity to the limit — not temperature itself, so a cool robot pays
  nothing.
- **Residual regularisation**: `−0.1 · ‖a_res‖²` — keep it a small correction.
- **Stage-2 training**: nominal frozen; motor temps randomly initialised
  `[T_max−25, T_max+10] °C`; ambient `[0, 35] °C`; payload `[0, 5] kg`.
- **Results**: A1 + 3 kg payload, overheat in ~5 min → **13+ min**, peak
  < 50 °C. From a hot 58 °C start on stairs/slopes, overheat rate **70 % →
  < 10 %**.

**Adapting to G2**: our gait is *already* residual-on-wkF. Add the per-joint
temperature estimate to the obs (from the sim thermal model in training; from
the Layer-1 I²t estimator at deploy), add `R_th`, and run a Stage-2 residual
finetune from `run20m_ppo` with randomised initial joint temperatures. Frozen
base, small residual, matches how every other continuation on this project has
been structured.

---

## 3. Sim testing plan

1. **Dynamic per-joint thermal model in the env** (8 leg joints). Lumped
   1-node: `T_j += dt·(k_gen·τ_j² − k_diss·(T_j − T_amb))`, `T_amb` randomised
   15–40 °C. When `T_j > T_trip`, drive the **existing `TORQUE_CUTBACK`
   mechanism** for that joint (reuse it — just switch the trigger from a random
   per-episode draw to the live thermal state). Start with a placeholder
   `k_gen`/`k_diss` tuned so a hard stance-hold trips in ~60–120 s; replace
   with bench-fitted values from §4.
2. **Thermal observation**: append normalised `T_j` (8) to the obs, plus a
   `hottest_joint` scalar + its rate. Behind a flag so the base policy's obs
   shape is unchanged until we commit.
3. **Long-episode eval** (this is deferred eval item 5, now with a purpose):
   2 000–4 000-step episodes, thermal model live. Metrics: time-to-first-trip,
   whether the policy sheds effort as joints warm, distance before a trip.
   Compare `run20m_ppo` (no thermal obs) vs a thermal-aware residual.
4. **Sustained-hold variant** in `robustness_sweep.py`: hold a hard stance /
   slow uphill with the thermal model on, report trip time per policy.
5. **Hardware validation** (hardware-gated): once bring-up allows, run the
   robot in a fixed hard stance (or one leg against a stop) until protection
   trips — log the time and the cooldown curve. Fit `k_gen`, `k_diss`,
   `T_trip`. This is the one measurement that turns the whole model from
   guesswork into a calibrated tool.

---

## 4. Shortcuts / what to skip

- **Skip real thermistors.** No spare ADC channels, no room, coreless servos
  don't have them. I²t estimation is the standard sensorless substitute and is
  good enough for a governor.
- **Skip the full 14-node thermal network** from the paper. Start 1 node per
  joint; add case↔ambient coupling only if the sim-vs-bench fit is poor.
- **Reuse, don't rebuild**: the `TORQUE_CUTBACK` mechanism (re-trigger from live
  `T`), the `FAC_POWER` penalty (already pushing the right way), the behaviour
  layer (governor), the residual architecture (Stage-2 finetune, base frozen),
  `robustness_sweep.py` (add the sustained-hold variant).
- **Fastest usable mitigation with zero training**: Layer 1 (I²t estimator +
  indicator) + Layer 2 (behaviour-layer governor + cooldown pose). Ship that
  first. Layer 3 (thermal-aware residual) is the "do it properly" follow-up and
  needs the sim model + bench data first.

---

## 4b. Retuning checklist — `pi_pipeline/gait/thermal_guard.py`

The guard is **built and wired** (`ThermalGuard` in `run_gait.py`, on by default,
`--no-thermal-guard` to disable). Every constant in it is a **PLACEHOLDER** tuned
by feel to be gentle — gentle flat walking never fires it, a sustained hard
session gets the spoken WARN at ~3 min, and only the 8-minute duty-cycle
backstop forces a lie-down on a long run. It has never seen real hardware.

**Retune once the bench test (§3.5 / §5.1) gives real numbers:**

| Constant | Now (placeholder) | Calibrate from |
|---|---|---|
| `_K_GEN` | 4e-3 | bench trip time — scale so `H` reaches `_H_TRIP` at the measured time-to-protection under a hard hold |
| `_K_DISS` | 0.010 (~100 s τ) | measured cooldown curve after releasing a hot servo |
| `_H_TRIP` | 60 (unitless) | rescale `H` to estimated °C once `_K_GEN`/`_K_DISS` are fit; set at the real protection threshold |
| `_WARN_FRAC` / `_COOLDOWN_FRAC` | 0.45 / 0.85 | how much margin the operator wants before the spoken warning / auto lie-down |
| `_MAX_CONTINUOUS_S` | 480 s | if real sessions never approach thermal limits in 8 min, raise it; if they do sooner, lower it |
| `_STALL_ERR_DEG` / `_STALL_SOFT_S` / `_STALL_HOLD_S` | 18° / 0.4 s / 1.5 s | real feedback-servo tracking error under a normal hard push vs an actual stall — set the threshold above the former, below the latter |
| `_SOFT_JOINT_SCALE` | 0.35 | how hard to ease a stalling joint toward neutral before giving up on it |
| `_STAND_DEG` | ±35° | replace with the actual `wkf_ref.npy` mean pose |
| effort proxy (`_K_VEL`, `_K_DEV`, `_GRAV_BOOST`) | 0.010 / 0.004 / 1.6 | if the feedback servos expose position readback, cross-check the proxy against measured tracking error; re-weight if a term is dead |

**Also:** `_speak_best_effort()` in `run_gait.py` currently prints and tries
`pi_pipeline.voice.tts.speak` — wire it to the real TTS path once the voice
stack import is settled. And `set_feedback()` is dormant until `run_gait.py`
actually reads `readAllFeedbackFast()` — the stall detector and the Petoi-style
soft cutback have no teeth until then.

## 5. Priority / sequencing

1. **Bench test on hardware** (when bring-up allows) → real trip time +
   cooldown constants. The one missing number.
2. **Layer 1 + 2** (I²t estimator, indicator, behaviour governor, cooldown
   pose) — no training, biggest risk reduction per unit effort, deployable
   without a policy change.
3. **Sim dynamic thermal model + long-episode eval** — validates and lets us
   iterate; feeds Layer 3.
4. **Layer 3 thermal-aware residual finetune** — the arXiv approach; best final
   result; needs 2 + 3 first.

Hardware-gated. Sits alongside Phase 8 / the pre-hardware backlog — not blocking
the current gait / course work.

---

## Sources

- [Petoi Bittle X specs](https://www.petoi.com/pages/bittle-x-robot-dog-with-arm-specifications) ·
  [Bittle servo set](https://www.petoi.com/products/quadruped-robot-dog-bittle-servo-set) ·
  [P1S datasheet request thread](https://www.petoi.camp/forum/hardware/bittle-p1s-servos-datasheet)
- [Petoi FAQ — servo protection reduces force on overcurrent](https://guide.petoi.com/faq-frequently-asked-questions) ·
  [`d` / REST command](https://guide.petoi.com/infrared-remote/remote-controller)
- [arXiv:2605.27046 — Motor thermal safety + quadruped locomotion, residual policy](https://arxiv.org/abs/2605.27046) ([HTML](https://arxiv.org/html/2605.27046))
- [maxon — I²t limitation & winding protection](https://support.maxongroup.com/hc/en-us/articles/4412763373970) ·
  [Synapticon — i²t overload protection](https://doc.synapticon.com/software/42/motion_control/advanced_control_options/i2t/index.html) ·
  [Ingenia — i²t protection](https://doc.ingeniamc.com/emcl2/command-reference-manual/protections/i2t-protection)
- [Coreless micro-servo failure modes — stall current, gear melt, brush wear](https://corelessservo.com/blog/how-to-choose-a-coreless-servo/) ·
  [Micro-servo current draw (idle/operating/stall)](https://microservomotor.com/common-specifications-and-parameters/micro-servo-current-draw.htm)
- [Machine Design — thermal safety margins / why temp sensors mislead](https://www.machinedesign.com/archive/article/21829526/thermal-safety-margins-for-servomotors)
- Local: [`hardware-specs.md`](hardware-specs.md) (P1S row, 5 A peak, "build in cooldown breaks")
