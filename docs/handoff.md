# Handoff — G2 Pi bring-up (2026-09-03, ~2 PM Eastern)

For a fresh Claude Code instance picking up the hardware bring-up. Written by the
Mac-side instance, which can no longer reach the Pi (see "Network" below).

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

## After bring-up (in order)

1. **Export `run20m_ppo` to ONNX** — needs the repo + the RL env
   (`stable_baselines3`, `pybullet`), so do it on the **Mac** (ask that instance)
   or on the PC with a cloned repo + venv. Then **numerical-parity check**: the
   exported model's actions must match the PyTorch policy's across a rollout.
   No export tooling exists yet — you may need to write it (`sb3` → `torch.onnx`).
2. **Get the ONNX file + control code onto the Pi.** Mac can't scp to the Pi
   directly (isolation) — route Mac → GitHub → Pi pulls, or Mac → PC → Pi.
3. **Wire the BiBoard** to the Pi: RX↔TX crossed, GND↔GND, Pi 5 V pin left
   **unconnected** (PiSugar powers the Pi). Then test the serial link
   (`pi_pipeline/link/` has `check_serial` / `ping`).
4. **`pi_pipeline/benchmark_pi.py`** — the full voice+API+serial benchmark
   (needs `pi_pipeline` deps installed; the audio wheels are the fragile part —
   see `pi-bring-up.md` §7).

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

- Pi bring-up: not started (or unknown — the script assesses).
- ONNX export of `run20m_ppo`: not started, no tooling yet.
- Mac↔Pi isolation: unresolved, workaround in place (use the PC).
- BiBoard not yet wired to the Pi.
