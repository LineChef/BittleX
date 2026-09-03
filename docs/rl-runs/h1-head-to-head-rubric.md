# H1 — Learned vs Scripted Gait: real-robot head-to-head rubric

**The question:** is `run20m_ppo` (the RL walking policy) actually better than
OpenCat's firmware `wkF` for plain walking on the real G2 — better enough to keep
building the RL locomotion track, or does G2 fall back to firmware gaits + a
perception layer?

This is backlog item **H1** (`hardware-gated-training-backlog.md`) and the gate
the whole RL locomotion effort hangs on. Run it once the gait runs at all
(`run_gait.py --cmd` produces a walk) — see the step ladder in
`docs/gait-deployment.md`.

Score with `pi_pipeline/gait/h1_score.py` (enter the measured numbers, get the
comparison table + verdict).

---

## Contenders

| id | what | how to run |
|---|---|---|
| **SCR** | firmware `wkF` + gyro-assist | `kwkF` over serial; gyro assist ON (its real advantage) |
| **RL**  | `run20m_ppo`, policy in full control | `run_gait.py --cmd <v>` (firmware balance OFF — it sends `g`) |
| **RL+b** | `run20m_ppo` *with* firmware gyro-assist underneath | `run_gait.py --cmd <v> --keep-firmware-balance` |

RL+b is a real deployment option, not just a curiosity — a second independent
balance loop under the policy may transfer better than either alone. Test all
three; the headline comparison is **SCR vs RL**.

---

## Conditions (the course)

Run every contender on each. Start easy; stop a contender early only if it's
clearly unsafe.

| id | surface / obstacle | why |
|---|---|---|
| C1 | hard flat floor | baseline — speed, heading, gait quality |
| C2 | low-pile carpet / rug | the real deployment surface; friction + compliance |
| C3 | a single ~15 mm threshold / door sill | the disturbance the sim's payload masked |
| C4 | a shallow board ramp, ~8–10° up, then down | slope handling |
| C5 | a few scattered ~20–30 mm obstacles (bottle caps, cardboard) | foot clearance / trip resistance |
| C6 | flat floor + a **measured** lateral shove mid-walk | stance recovery — the Phase-4 question, finally on hardware |

For C6, "measured" = a repeatable push: a small weight on a string swung from a
fixed drop, or a luggage scale pulled to a target force (record the peak). Same
push for every contender.

---

## What to measure, per (contender × condition)

**N ≥ 5 runs each.** Alternate contenders run-to-run (SCR, RL, RL+b, SCR, …) so
battery droop and servo warm-up hit everyone equally. One battery charge per
session; note the surface temperature (servo torque drifts with heat).

| metric | how | notes |
|---|---|---|
| **forward speed** (m/s) | mark a 1.0–1.5 m lane; time from start line to finish line (phone stopwatch or video frame count) | for SCR use its natural speed; for RL command the speed that *matches* SCR's measured speed **and** also RL's own "cruise" (0.10) — report both |
| **heading drift** (deg) | lateral offset at the finish line ÷ lane length, → `atan` | + or − (which way it curves) |
| **fall rate** | falls ÷ N runs on that condition | a "fall" = body on the ground / needs manual reset |
| **recovery (C6 only)** | of the shoves that caused a visible stagger, fraction where it caught and kept walking without a fall; eyeball time-to-resettle (video) | this is H4's real answer too |
| **gait quality** (0–3) | video review: 3 = clean diagonal trot, feet clearing, low body bounce; 0 = dragging / stumbling / hopping | score blind if you can (rename clips) |
| **power / endurance** (proxy) | PiSugar S has no telemetry — use an inline USB power meter on the BiBoard 5 V feed if you have one, else: time to first brown-out walking continuously on C1, one run each | rough; a tie-breaker, not a headline |
| **the "can't" column** | does the contender do it *at all*: hold a commanded speed (creep 0.04 / fast 0.14), stand on command, walk backward, hold heading to <5°? | SCR structurally can't; RL's whole value proposition |

Log raw runs (a notebook row per run: contender, condition, run #, time, offset,
fell y/n, notes). `run_gait.py --log` writes the RL runs' per-tick IMU +
commands automatically for later `real_vs_sim.py` analysis.

---

## The decision

Capability bar (`feedback_training_capability_bar.md`): the whole-effort target
is **"scripted+"** — beat scripted on every cell **and** do what it can't.

**KEEP building on RL locomotion if:**
- RL matches or beats SCR on **fall rate** on every condition (no new failure
  modes), **and**
- RL is clearly better on **≥ 2 of** {speed at matched command, heading drift,
  gait quality, C6 recovery, obstacle/threshold handling}, **and**
- RL delivers the "can't" column — speed command, stand, backward, heading-hold —
  which it structurally does if the transfer works at all.

**FALL BACK to firmware `wkF` + perception layer if:**
- RL falls more than SCR on any everyday condition (C1/C2/C3), **or**
- RL is not meaningfully better than SCR on anything except the command
  interface — i.e. the sim-trained control doesn't survive contact with real
  servos, and the only thing RL buys is a speed knob that isn't worth the
  fragility.

**Middle result** (RL walks, transfers okay, isn't clearly better): keep
`run20m_ppo` as a fallback, do **one** sim-to-real ID pass (below) + a targeted
retrain against the measured servo/mass model, and re-run H1 once. If the second
pass doesn't move it, fall back.

---

## Pairing: sim-to-real system ID

The head-to-head answers "does it transfer." The ID tooling answers "*why*, and
what to fix" — run it in the same session:

1. **`sysid_collect.py`** (Pi) — runs a fixed calibration sequence (defined
   static poses held under gravity + a slow open-loop `wkF` cycle) while logging
   the `V` IMU stream + every command sent. Also `run_gait.py --log` during the
   H1 walks.
2. **`sysid_replay.py`** (Mac) — replays that exact command sequence **open-loop**
   in the sim env (feed the recorded joint targets straight to the servos, no
   policy) and diffs the resulting body-tilt / angular-rate trajectories against
   the real IMU log. The gap = the sim-to-real gap, per metric, no joint
   feedback required.
3. **`sysid_replay.py --fit`** — sweeps the sim's actuator params
   (`maxForce`, position/velocity gains, a command-latency term via
   `CMD_LATENCY_STEPS`) to minimise that trajectory gap. Output: the corrected
   sim model to retrain against if H1 lands in the "middle result".

---

## Session checklist

- [ ] Full battery; note start voltage if measurable.
- [ ] Surfaces C1–C5 set up and marked (lane length recorded).
- [ ] C6 push rig calibrated (peak force recorded).
- [ ] `run_gait.py --dry-run` passed on the Pi (80 Hz holds).
- [ ] `run_gait.py --probe-imu` → `parse_imu_line` matches the real format.
- [ ] `run_gait.py --openloop` → servo signs verified, `deploy_map.SERVO_SIGN` set.
- [ ] Phone on a tripod for consistent video framing.
- [ ] Notebook / sheet ready for raw run rows.
- [ ] `sysid_collect.py` run first (fresh servos), before the walks warm them up.
