# When the hardware arrives — ordered bring-up

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> the ordered day-1 bring-up sequence (the executable version is `python -m pi_pipeline.bringup`). Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## When the hardware arrives — ordered bring-up

The phases above are grouped by system; this is the sequence to actually work
through once the Bittle X + BiBoard land (the Pi bring-up is already done — see
Phase 6). The camera arrived first and its bench bring-up is done (Phase 8).

> **2026-09-20 — pre-arrival research pass against Petoi's official docs.**
> Cross-checked this sequence against the actual Bittle X V2 user manual
> (calibration/first-power-on pages) rather than just firmware source —
> findings + sourced corrections in
> [`hardware/calibration-and-bringup-research.md`](../hardware/calibration-and-bringup-research.md).
> Highlights: pre-assembled units are only **coarse**-tuned (calibration is
> routine, not conditional); joints need to match a specific bootup posture
> *before* first power-on; a stuck-feeling new joint is usually gear
> protection engaging, not a fault; and the real calibration-entry serial
> token is bare `c`, not `c16` (fixed below and in `bringup.py`; verify
> against the real board once serial is up either way, since
> `check_serial` blocks both by design and neither has been sent for real
> yet). **Known desync flagged, not yet fixed**: `pi_pipeline/bringup.py`'s
> step IDs/order still reflect the pre-Phase-0-split flat list (e.g. its
> step 2 "weigh the build" still precedes its step 4 "wire Pi↔BiBoard",
> the opposite of this doc's Phase 0/Phase 1 split, where weighing is
> gated on the Pi already being wired to the frame) — the restructuring
> below was never propagated into the interactive tool. Worth a dedicated
> pass to renumber `bringup.py` to match before bring-up actually starts,
> so the tool and this doc agree.

**Staged in two phases, gated on the Pi.** Phase 0 below is deliberately
everything that can be ruled out with *only* the bare Bittle X + BiBoard —
frame assembly, servo calibration, and a full movement sweep — none of it
touches the Pi, PiSugar, or camera at all. That's a real checkpoint, not just
a reordering: it isolates mechanical/servo/BiBoard problems from
Pi-stack problems before the two are ever combined on the frame, while the Pi
+ PiSugar + clip assembly is bench dry-fit and de-risked independently
(off-frame). Everything from Phase 1 on is gated on "the Pi is now physically
wired to the frame" and picks up the original step order (weighing,
serial link, voice, RL, vision, integration) unchanged in substance —
only renumbered.

> **Rule: stay on the calibration stand through step 13a. No floor time before
> then.** Everything through "verify servo signs" — assembly, calibration,
> first movement, voice, the RL joint-control bench, IMU probing, open-loop
> gait verification — happens with G2 supported on the stand, weight off its
> feet. That's deliberate: servo sign, the real IMU format, and payload weight
> are all genuinely unknown until the real robot is in hand (see "Known risks
> / honest expectations" below), and on the stand a mistake in any of them is
> at most a flailing leg, not a fall or a walk off an edge. The floor is
> earned once `--openloop` confirms the servo signs are right — that's the one
> thing that actually requires ground contact to test honestly (H1, step 13b).
>
> **2026-09-28 — stand mismatch.** Petoi shipped the Nybble calibration
> stand, not the Bittle one; it doesn't fit G2 cleanly. Order the correct
> one in parallel. In the meantime, the actual hazard this rule guards
> against is *our own* joint commands with an unknown servo sign
> (`run_gait.py --openloop`, the RL joint-control bench) — stock-firmware
> postures/gaits like `vtF` are Petoi-designed for normal floor operation,
> so observing those on the floor is a reasonable stand-in for now. Keep
> the no-floor-time rule for anything past step 13a (our own control code)
> until a stand (correct or improvised) is in place.

**Diagnostics-mode impact of the Phase-0 split.** Checked this directly
against `pi_pipeline/diag/core.py` and `check_serial.py` rather than assuming:
session logging (`diag.event`, `events.jsonl`, `manifest.json` under
`~/g2_logs/`) is **not** Pi-gated — it's a plain module-level singleton that
auto-starts its own session on first `event()` call (`Diag.event_locked` →
`start_session("auto")`), and `check_serial`'s `allmoves` already calls
`diag.event(...)` directly for the idle-baseline read and every per-move
voltage/latency line. That means `allmoves`, run completely standalone from a
dev machine with nothing but a serial cable to BiBoard, gets the **exact same**
diagnostic logging it would get running through the full `pi_pipeline.app` on
the Pi — nothing about Phase 0 is diagnostics-degraded. The one piece that
*is* Pi/voice-gated is the **spoken** `diagnostics_query` tool (it lives in
`voice/conversation.py`, needs the running app); the underlying
`summarize_session()` / `last_failure()` it speaks from work identically from
the CLI (`python -m pi_pipeline.diag summarize`) with no Pi involved. Given
that, `allmoves` — the comprehensive "cycle everything, log voltage +
latency" test — moves *up* into Phase 0 rather than getting a new, weaker,
unlogged stand-in: it needs a serial connection to BiBoard, not a Pi, so it
runs against BiBoard's own USB port from a laptop (temporarily set
`G2_SERIAL_PORT` to that port, not the eventual Pi value). It then runs
**again**, unmodified, once the Pi is wired in (Phase 1, step 8) — same
command, same event schema — specifically so the two sessions' `events.jsonl`
can be diffed to see whether adding the Pi + PiSugar's weight and wiring
measurably changed battery sag or reply latency on any move. That diff is a
concrete, evidence-based answer to "did adding the Pi stack change anything
mechanically," not a guess.

**Phase 0 — bare hardware, no Pi in the loop**
1. Assemble Bittle X V2. Match joints to the bootup posture in Petoi's
   unboxing diagram *before* first power-on. Ships only **coarse**-tuned
   (not fully calibrated) — plan on step 2's calibration pass, don't treat
   it as conditional. A joint that feels stuck despite a correct command is
   likely new-gear protection, not a fault — rotate it by hand first.
2. **On the calibration stand, before it touches the ground:** full
   range-of-motion pass by hand / `check_serial` (watch for binding / leg-on-leg
   collision), then firmware `c` auto joint calibration (also enterable by
   powering on with the robot tilted one side up, if serial/app isn't
   ready yet). Safe place for first
   power-on. Detailed gait steps: [`guides/gait-deployment.md`](gait-deployment.md) step 6.
3. **Still on the stand, BiBoard's own USB port, no Pi wired:**
   `python -m pi_pipeline.link.check_serial ports` → set `G2_SERIAL_PORT` in
   `.env` to that port → `firstmove` (guided, confirmed, one joint at a time) →
   once that's clean, `send kbalance` → `skills` → `allmoves` (cycles EVERY
   move G2 knows — skills + the autonomous-behaviour gestures + sleep + carpet
   gait + the recovery/get-up keyframes, logging battery voltage + reply
   latency per move against an idle baseline, same as it always did — see the
   diagnostics-impact note above). A clean pass here is the actual "base
   hardware ruled out" checkpoint — note this session's ID
   (`~/g2_logs/<session_id>/`) as the pre-Pi baseline to diff against later.
   *(In parallel, off-frame: bench dry-fit the Pi + PiSugar + clip assembly to
   de-risk that build independently — see
   [`blueprints/biboard-pi-connector.md`](../../blueprints/biboard-pi-connector.md).)*

**Phase 1 — the Pi is now physically wired to the frame**
4. **Weigh the final build** on a kitchen scale, with the Pi + PiSugar S + camera
   + mount actually on the robot. Weigh the **camera cluster and the PiSugar S
   battery separately** (the battery is >½ the current spine estimate; if it
   mounts somewhere distinct, it needs its own sim body). Balance each piece on
   an edge for height + fore/aft CoM. Then set `PAYLOAD_MASS_*` / `HEAD_MASS_*` /
   positions in `opencat_gym_env.py` and retrain (or `--finetune-lr`) if the
   delta from ~76 g is real — [`rl/hardware-gated-backlog.md`](../rl/hardware-gated-backlog.md) **H2**.
5. Wire Pi ↔ BiBoard **data-only** (RX/TX/GND); PiSugar S is the sole power
   source. Confirm the back cover still fits.

**Serial link (Phase 5) — still on the stand**
6. `python -m pi_pipeline.link.check_serial ports` → set `G2_SERIAL_PORT` in
   `.env` back to the Pi's port (likely `/dev/ttyS0` → `/dev/ttyAMA0` after
   `disable-bt`).
7. Enable Serial-2 on the BiBoard (`XS`, or edit `OpenCat.h` + reflash).
8. `python -m pi_pipeline.doctor --serial` (passive handshake; **note the firmware
   version** in the `?` banner — the gait's command-timing model and 5 Hz IMU throttle
   were traced from OpenCatEsp32 source as of 2026-09-08) → **on the stand:**
   `check_serial firstmove` again, now through the Pi → once clean, `send kbalance`
   → `skills` → **`allmoves` again** (same command as Phase 0 step 3, now
   through the Pi's wiring) — diff this session's `events.jsonl` against the
   Phase 0 baseline for a voltage/latency delta from the Pi stack.

**Voice (Phase 7) — still on the stand (nothing here needs the floor)**
9. `python -m pi_pipeline.voice --mode text` → Claude + memory end-to-end (key is
   already set).
10. `check_audio wake` / `stt` on the Pi's mic → tune `G2_WAKE_WORD`,
    `G2_STT_SILENCE_S`. `--mode voice --actuator serial` for the full loop.
11. `benchmark_pi.py` on the actual Pi — confirm `en_US-ryan-low` + Vosk hit
    real-time on 512 MB. If sluggish: shorter `CLAUDE_MAX_TOKENS`, streaming TTS,
    a longer "thinking" cue.

**RL sim-to-real (Phase 6 — stack already built + sim-validated) — still on the stand**
12. `pi_pipeline/gait/bench_real.py` — real-time joint control on the Pi (sim
    bench: 0.43 ms/step).
12a. **Deploy the release-candidate policy (±30°), not `run20m_ppo` (±22°).**
    The residual scale now travels with the policy file: `export_onnx.py` writes
    `<policy>.onnx.json` (`residual_scale_deg`) and `residual_policy.py` reads it
    (legacy fallback 22 only when no sidecar exists). Deploying = set
    `DEFAULT_POLICY` in `residual_policy.py`, rsync the `.onnx` **and** its
    `.onnx.json` to the Pi together, and confirm on the dev machine first with
    `validate_deploy.py --onnx <policy>.onnx` ("ALL OK" — it pins the sim to the
    sidecar's scale). Check the log line `residual scale: 30 deg`.
12b. **Check whether `i` echoes on completion — if so, send only the freshest target.**
    When commands back up, the firmware runs the *oldest* waiting one and drops the
    rest (`read_serial()` keeps the first command it reads), so streaming at 80 Hz
    means lag (~55 ms in the sim model) and stale targets. Source shows a token echo
    after each finished command (`printToAllPorts(token)` in `reaction.h`), but some
    move paths have it commented out — **measure it on the real board**: send a few
    `i` moves with the IMU stream off and log what comes back and when. **If `i`
    echoes reliably:** switch `run_gait.py` to send-on-acknowledgement (hold only
    the newest target, send it when the echo arrives, time out and resend if an echo
    is lost), update `firmware_model.py` to match, measure the real lag, and retrain
    the gait under the shorter lag (the sim suggests roughly half: ~15–30 ms). **If
    it doesn't:** keep streaming; the firmware-side fix (keep the newest command)
    would need a fork — revisit the no-fork decision only if the measured lag hurts.
13a. **On the stand:** `run_gait.py --probe-imu` (confirm the real IMU format —
    genuinely unknown until now) → `--openloop` (verify servo signs against
    `deploy_map.py`'s `SERVO_SIGN` — a flipped sign must be caught here, not on
    the floor). Do not proceed to 13b until this is clean.
13b. **Now the floor, for the first time:** `--cmd` (the learned gait) →
    **the H1 head-to-head** vs firmware `kwkF`. Methodology + decision rule:
    [`rl/h1-rubric.md`](../rl/h1-rubric.md); `h1_score.py` produces the verdict.
    Emergency stop (`--halt` / "emergency stop") within reach the whole time.

**Vision on the robot (Phase 8)**
14. Mount the camera on G2, train the **desk-edge classifier** on the real
    mounted POV (B16 — highest priority), wire `Avoider` decisions to the
    actuator, build the `CliffGuard` reflex against the trained classifier.

**Integration (Phase 10)**
15. Voice + vision + memory concurrently; resolve timing/resource conflicts
    (historically the messiest phase). Then revisit locomotion with perception in
    the loop toward the Phase 8 Target capability.

---
