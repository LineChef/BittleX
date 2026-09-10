# Get-up sim replay (H9) — 2026-09-10

The hardware-gated backlog's one **do-now** item for self-righting: replay the
firmware get-up keyframes in PyBullet and see whether they *plausibly* work,
before the real robot is here to test them.

Script: `rl_training/opencat-gym/reference_gait/verify_getup_reference.py`
(`python verify_getup_reference.py --gif --sheet`). Outputs in that folder:
`getup_prone_flat.gif`, `getup_supine.gif`, `getup_contact_sheet.png`.

## What was replayed

- **`rc`** ("recover") — the firmware self-right for a side / front fall.
- **`rl`** ("roll") — flips a supine robot onto its side; firmware then chains
  `rc`. So supine = `rl` → `rc`.

Both decoded from `InstinctBittleESP.h` by `build_skill_reference.py rc rl` →
`rc_ref.npy` / `rl_ref.npy`, (100, 8) rad, URDF joint order. Driven open-loop
through the 8 leg joints via `POSITION_CONTROL` (`FORCE = 0.40` N·m/joint, above
`verify_wkf`'s 0.2, in the spirit of Run 6's torque boost).

## Result — 0 / 2 recovered

| fall state | start \|roll\|/\|pitch\| | end \|roll\|/\|pitch\| | end z | verdict |
|---|---|---|---|---|
| prone, belly-down flat | 0.00 / 0.00 | 0.00 / 0.00 | 0.022 m | **no** — `rc` reaches a transient 4-leg crouch mid-play (tilt-sum hits 0.0) then collapses flat again |
| supine, on its back | 3.14 / 0.00 | 3.02 / 0.07 | 0.030 m | **no** — `rl` → `rc` flails the legs; the roll-over never happens, ends still on its back |

## Why this is expected, and what it does / doesn't tell us

The replay is a **crude lower bound**, and a poor result was the predicted
outcome, not a surprise:

1. **The refs are approximate.** `rc`/`rl` decode as *behaviours* — 5–6 keyframes
   resampled to 100, with the per-frame timing params dropped and the
   **IMU-triggered mid-sequence waits removed** (`skill.h` `imuException`
   checks). The real skill is not a smooth 100-step interpolation.
2. **Open-loop.** On the real robot `rc` runs *with the gyro-balance layer
   active* (`gyroBalanceQ`), which is exactly what would hold the transient
   stand that `rc` reaches in the prone case. The sim replay has no such loop.
3. **No stable side-lie or nose-down rest in this URDF** (measured: a mild tip
   flops back belly-down; anything past ~1.1 rad roll goes fully supine). The
   real Bittle rests stably on its flank / face — the poses firmware `rc` is
   actually designed for. The sim can only present "belly-flat" and "supine".
4. **Bare `plane.urdf`** — no carpet-like friction/compliance for the feet to
   push against.

**Takeaway for the hardware plan (H9 / project-plan.md "Recovery"):** the sim
cannot validate the firmware get-up — it neither confirms nor rules it out.
Treat `krc` / `krl` as *unverified* on arrival:

- enable gyro assist (`g`) first — the prone-case transient stand suggests `rc`'s
  posture is roughly right and just needs the balance loop to hold it;
- test stock `rc` / `rl` against the fall types real RL sessions actually
  produce, and expect to re-author them in Skill Composer;
- a fall-orientation classifier (IMU roll/pitch → which recovery) is still
  needed — `RecoveryFSM` in `pi_pipeline/link/recovery.py` is the seam.

Consistent with the standing conclusions: no roll-axis DOF (learned self-right
impossible, Run 6), firmware self-right covers slow falls only, and contact-rich
scripted skills hit a sim-fidelity wall in PyBullet (cf. the `cmh` climb, Phase
F). See `docs/hardware/self-righting.md`.
