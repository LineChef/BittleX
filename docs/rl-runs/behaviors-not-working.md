# Behaviors we couldn't get working (yet)

Running list of motor behaviors we tried and could not make work, with why and
what would change the verdict. Add an entry whenever an effort is abandoned.

---

## CLIMB / mount a ledge — sim-fidelity wall (Phase F, 2026-09-08)

**Goal:** G2 gets its whole body up onto a step/ledge ≥ ~3 cm.

**Tried:**
- From-scratch PPO (Runs 1–2) → "stand still, do nothing" reward optimum, then reward hacking.
- Residual on a scripted base — 6 base designs: front reach-and-plant, rear-up-then-push, scrabble/claw-and-mantle, "rear up like a horse".
- **Petoi's own `cmh` (climb) keyframe** decoded from OpenCat `InstinctBittleESP.h` and played open-loop.
- Sweeps: approach standoff 0.3–4.3 cm, ledge height 2.5–4.5 cm, joint torque 2.6→6.5, paw/ledge friction 0.5→2.0.

**Result:** nothing climbs a ≥ 2.5 cm ledge in PyBullet. Body rises ≤ 1.1 cm and
usually drifts *backward*. Even Petoi's tuned `cmh` fails here.

**Why (measured):**
- Front paw reaches ~7 cm forward of rest, but only at **z ≈ 0.8 cm** — can't get the paw *up* onto a 3 cm+ edge.
- Max "horse-rear" pitch is **~10–13°**, and the body *crouches* (z 0.077→0.059) instead of rearing — the legs can't pivot the body nose-high.
- Pawing at the vertical face nets a backward push, no hook.
- `cmh` was tuned on the **real robot** (foot-rubber grip, servo compliance, a human sending realtime nudges over Bluetooth) — the forum itself calls it "not robust to configuration". The sim's box-contact model doesn't reproduce the grip.

**What would change it:** hardware. Port `cmh` (`reference_gait/cmh_ref.npy`) to the
real robot, tune the approach distance + keyframe against a real step, *then*
consider a residual policy on real IMU data. A genuinely dynamic hop (`jpF`) is
the other untested avenue and needs torque/impulse control, not position keyframes.

**Kept:** `climb_env.py` / `train_climb.py` / `eval_climb.py` / `climbwatch`
(reusable harness), `cmh_ref.npy`, and the diagnosis above. On the
hardware-gated backlog.

---

## Learned vision-in-the-policy (Phase D + smoke_vfix3, 2026-09-07/08)

Covered in `vision-goal-locomotion-plan.md`. A from-scratch vision-conditioned
walk either **plows** at commanded speed (speed-track hard) or **stalls** to a
crawl (speed-track soft). Reward-shaping "see it → step over it" into a
bounded-residual walk at 3 M does not work. **Closed.** Path is scripted
skill-switching on the frozen walk (Phase E).

---

## Self-righting from fully on the back (sim, pre-2026-09)

Covered in `docs/research/self-righting-research.md` and the memory. Would not
train in PyBullet. **The real Bittle X CAN do it** (observed 2026-09-07) — this is
a sim-fidelity gap, not a physical limit. Firmware has a scripted self-right
(`rc`) for slow falls. Revisit = close the sim gap or use `rc` on hardware; do
**not** re-conclude "impossible".
