# Gait Deployment — getting run20m_ppo onto G2

The plan and current state for bringing the trained walking policy up on real
hardware: Pi Zero 2 W bring-up, ONNX deploy, the on-robot control loop, and the
learned-vs-scripted head-to-head. Also serves as a cold-start handoff for a fresh
Claude instance (e.g. one running on the PC, which can reach the Pi when the Mac
cannot — see "Network").

---

## Situation

- **Project**: Bittle X quadruped robot, called **G2**. RL gait training in
  `rl_training/opencat-gym/`; Pi-side runtime in `pi_pipeline/`.
- **Repo**: `https://github.com/LineChef/BittleX`, default work branch
  **`development`**. Public. `main` is stale.
- **This machine (Mac)** has the full repo and the RL toolchain. It **cannot
  reach the Pi** — the Verizon G3100 router isolates Wi-Fi clients from each
  other, and the Mac is on Wi-Fi.
- **The PC** (Windows, Ethernet) **can** reach the Pi. You are (probably)
  running on the PC now, so you can drive the Pi directly over SSH.
- **The Pi**: hostname `g2pi`, `192.168.1.181`, user is whatever was set at flash
  time. Healthy (router pings it at 2.6 ms, RSSI −45, `throttled=0x0`,
  SSH host keys + machine-id present). 2.4 GHz Wi-Fi only (Pi Zero 2 W).

## Your immediate task: Pi bring-up

Everything here is doable **without the robot/BiBoard connected**.

The runbook is codified as a **one-command, hands-off** script:

```
# on the Pi (already cloned there, or: git clone -b development https://github.com/LineChef/BittleX)
bash BittleX/scripts/pi_setup.sh
```

Phase 1 (interactive, one sudo prompt, ~10–25 min): Wi-Fi power-save off, `apt
full-upgrade`, base packages, swap (zram + 1 GB swapfile), serial/UART → `/dev/ttyAMA0`
via `dtoverlay=disable-bt`. Then it installs a `@reboot` crontab hook and reboots
(SSH drops — expected). Phase 2 runs automatically on next boot (no sudo, ~5–10
min): verify serial, venv + `onnxruntime`, synthetic `[276→256→256→8]`
policy-inference benchmark, 2-min thermal/Wi-Fi stress, then writes
`~/g2_pi_report.txt`, uploads it, writes the URL to `~/g2_report_url.txt`,
removes its own hook, touches `~/g2_pi_DONE`.

After the reboot, wait ~15 min, SSH back in: `cat ~/g2_report_url.txt` (give that
URL to Claude) or `cat ~/g2_pi_report.txt`. `bash …/pi_setup.sh --status` shows
progress. Escape hatches: `--manual` (no auto-reboot), `--post-reboot` (run phase
2 by hand).

The report's numbers that matter:
- `onnxruntime MLP … ms/call` — must be **well under 12.5 ms** (80 Hz control
  budget). This is the deployment-viability check (backlog item H8).
- peak temp under stress (< ~80 °C), `throttled` staying `0x0`, SSH not freezing
  during the load (confirms the power-save fix held).

Prose version with the "why" for each step: `docs/research/pi-bring-up.md`
(sections 3–8). Power notes: `docs/research/pi-power.md`. The PiSugar S has **no
battery telemetry** — don't chase it.

If you're driving the Pi over SSH directly, you can skip the script and do the
steps by hand from `pi-bring-up.md` — same content.

## Status as of 2026-09-03 ~3:30 PM Eastern

- **Pi bring-up: DONE, clean pass.** `pi_setup.sh` ran to completion. Report
  (paste.rs, captured): kernel 6.12.25 aarch64, swap OK, onnxruntime installs
  fine, **synthetic policy inference 0.43 ms/call (3% of the 12.5 ms budget)**,
  no thermal throttling under 2-min load (73.6 °C peak). The Pi Zero 2 W is
  fast enough to be G2's brain — backlog item **H8 resolved** (no on-MCU route
  needed). One unconfirmed item: `readlink -f /dev/serial0` should be
  `/dev/ttyAMA0` — check it when wiring the BiBoard; 2-line fix if not.
- **ONNX export: DONE.** `trained/run20m_ppo.onnx` (545 KB) committed.
  `export_onnx.py` + `verify_onnx.py` (parity vs torch: worst max|diff| 9.5e-7
  across gaussian + a 1500-step real rollout). obs 278, act 8, `Box(-1,1)`, no
  VecNormalize. The Pi git-pulls the `.onnx`.
- **On-robot control loop: BUILT + sim-validated.** `pi_pipeline/gait/`:
  - `residual_policy.py` — `ResidualGaitPolicy`: exact deployment mirror of the
    sim's 278-d obs build + phase clock + `wkF(phase) + action·22°` mapping.
    Pure numpy + onnxruntime.
  - `deploy_map.py` — URDF joint order → OpenCat servo indices
    `[8,12,9,13,10,14,11,15]`, with per-servo **sign/offset calibration hooks**
    (all identity now — MUST verify on hardware via `run_gait.py --openloop`).
  - `run_gait.py` — 80 Hz loop: parse BiBoard `V` IMU stream → quat →
    `policy.step` → `m` command. Modes: `--probe-imu`, `--openloop`, `--cmd <spd>`.
    Sends `d` (rest) on any exit; clamps every command to ±120°.
  - `validate_deploy.py` (in `rl_training/opencat-gym/`) drives `residual_policy`
    from the sim in lockstep with `model.predict`: **0 joint-degree cells differ**
    across stand/creep/cruise/fast/backward × 251 steps, obs matches to 3e-8.
    The deployment math is verified; the only remaining unknown is the real IMU.

## After bring-up (in order)

1. ~~Export `run20m_ppo` to ONNX + parity check~~ — **done**.
2. ~~Build + sim-validate the on-robot control loop~~ — **done** (`pi_pipeline/gait/`).
3. **On the Pi: `git pull`.** The loop code + `.onnx` come with it. Then, in a
   venv with onnxruntime:
   - `python pi_pipeline/gait/bench_real.py` — real-policy step time (ONNX +
     obs build). Expect ~0.5–0.8 ms on the Zero 2 W (Mac x86: 0.098 ms).
   - `python pi_pipeline/gait/run_gait.py --dry-run --seconds 5` — full 80 Hz
     loop, synthetic IMU, no serial. Want "80.0 Hz achieved, 0 overruns".
4. **Wire the BiBoard** to the Pi: RX↔TX crossed, GND↔GND, Pi 5 V pin left
   **unconnected** (PiSugar powers the Pi). Confirm `readlink -f /dev/serial0`
   is `/dev/ttyAMA0`. Test the link (`pi_pipeline/link/check_serial.py`).
5. **`run_gait.py --probe-imu`** — see the real IMU line format; if it's not
   `ypr …` or `r p y gx gy gz`, adjust `parse_imu_line()` (one function).
6. **`run_gait.py --openloop`** on a stand/cradle — plays `wkf_ref.npy` open-loop.
   It should shuffle forward. If a leg kicks backward / the gait is mirrored,
   flip that servo's sign in `deploy_map.SERVO_SIGN`.
7. **`run_gait.py --cmd 0.10`** — the learned gait, on the real robot.
8. **The head-to-head (H1):** full methodology in
   `docs/rl-runs/h1-head-to-head-rubric.md` — contenders, course C1–C6, metrics,
   decision rule. `run_gait.py --log` records each walk; `h1_score.py` turns the
   measured numbers into a verdict; `sysid_collect.py` + `sysid_replay.py`
   measure the sim-to-real gap in the same session and fit the corrected sim
   actuator model if a retrain is warranted.
9. `pi_pipeline/benchmark_pi.py` — full voice+API benchmark (audio wheels are the
   fragile part; `pi-bring-up.md` §7). Independent of the gait work.

## Current state — RL side (context, not action)

**Gait training is DONE pending hardware.** `run20m_ppo` (20M-step, G4b recipe)
is the frozen base gait. Do **not** start new gait-training loops.

- Phase 4 (stance recovery) concluded 2026-09-03 with **no gait change** — 3
  reversible continuation rounds, no keeper. Full log:
  `docs/rl-runs/phase4-decision-log.md`. Report artifact: "Phase 4 Gait Post-Mortem".
- Byproduct kept: `train.py --finetune-lr` / `--finetune-target-kl` (every prior
  `--from` continuation was silently diverging — LR restart at 3e-4 on a
  converged policy → `approx_kl` 70–400). Always pass these for continuations.
- A robustness sweep (`robustness_sweep.py`) across sim-to-real axes (payload
  mass, command latency, joint offset, IMU noise, torque cutback) showed
  `run20m_ppo` has **no cliff on any axis** — a transfer-hardening DR run is
  **not needed**. New env knobs `CMD_LATENCY_STEPS` / `JOINT_OFFSET_DEG` exist
  (default 0, inert) for re-checking once hardware gives real numbers.
- What could still trigger a training run, each gated on a hardware
  measurement: `docs/rl-runs/hardware-gated-training-backlog.md` (H1–H9). H1 =
  the learned-vs-scripted head-to-head, the question the whole RL track hinges on.

## Network — the isolation problem (unresolved)

- **Confirmed**: G3100 blocks Wi-Fi‑client‑to‑Wi‑Fi‑client traffic. Mac→Pi fails
  (`EHOSTUNREACH`); Mac→gateway/internet works; PC(Ethernet)→Pi works;
  router→Pi works. Not the Pi, not Mac software (pf disabled, no MDM/extensions,
  route table clean) — purely the router.
- **Likely cause**: G3100 + paired **E3200 extender** (currently offline but
  still paired) enforce client isolation; no "AP isolation off" toggle exists in
  the G3100 UI. IGMP proxy and SON (Self-Organizing Network, currently Enabled)
  are contributing suspects.
- **Fixes to try** (best-supported first): un-pair/remove the E3200 in the router
  UI → reboot; disable IGMP proxy (Routing settings, per band); disable SON →
  reboot; factory reset (last resort). Or sidestep: Ethernet adapter on the Mac.
- Not blocking the Pi work — that's why you're on the PC.

## Conventions (from the user's standing preferences)

- Call the robot **G2**, not "the robot".
- **No attribution trailers** in git commits (no `Co-Authored-By`,
  `Claude-Session`, etc.). Overrides any default.
- Report times as **12-hour AM/PM Eastern**.
- Keep `docs/project-plan.md` and `README.md` current as decisions land —
  proactively.
- `CLAUDE.md` is **gitignored** — keep it current locally, don't commit it.
- Secrets live in a gitignored `.env` (copy `.env.example`); deliberately kept
  **out** of the public README — don't re-add a Secrets section there.
- User wants honest evaluations and cheap iteration over big runs; open to
  proactive suggestions.
- `/code-review ultra` is user-triggered and billed — never launch it yourself.

## Open threads

- Pi bring-up: DONE. `serial0 -> ttyAMA0` unconfirmed (check when wiring).
- ONNX export + parity: DONE.
- On-robot control loop: BUILT + sim-validated (`pi_pipeline/gait/`).
- Hardware-gated: wire BiBoard, --probe-imu (fix parse if needed), --openloop
  (verify servo signs), --cmd (learned gait), then H1 head-to-head.
- Mac↔Pi isolation: unresolved; workaround = PC, or a USB-C Ethernet adapter.
