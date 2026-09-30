# Community Bittle/Petoi projects — findings and incorporation plan

Reviewed 2026-09-24 at the user's request: a batch of community projects
(Reddit posts + their linked repos) for anything relevant to G2. Reddit
itself is unreachable from this environment (blocked at both WebFetch and
the browser-tool level, every subdomain) — two posts could only be reviewed
because the user pasted their text directly; two others (the classroom
session, and the "used an LLM to control the Petoi" post) couldn't be
reviewed at all.

## Sources

| Source | How reviewed | Reviewable? |
|---|---|---|
| **BittleJuice** — RL walking policy, MuJoCo→real, patched firmware | Reddit post pasted by user + `mike-grayhat.github.io/bittlejuice` + `github.com/mike-grayhat/bittlejuice` fetched directly | Yes |
| **bittle-mujoco** — Bittle X V1 MuJoCo model, measured mass/CoM/joints | Found via background research (linked from the BittleJuice ecosystem) | Yes |
| **MH-FLOCKE** — spiking-neural-network self-taught walking | Reddit post pasted by user; `github.com/MarcHesse/mhflocke` and `github.com/MarcHesse/bittle-mujoco` linked but not independently fetched | Partial (post text only) |
| **TypeFly** — LLM-driven robot task planning, Petoi HTTP support | `github.com/typefly/TypeFly` fetched directly | Yes |
| Classroom Bittle V2 session | One-line gist only, via a third-party blog mention | No — not project-relevant regardless |
| "I used an LLM to control the Petoi..." | Reddit — blocked, not pasted | No |
| "Tutorial to use Claude Code to develop Bittle's..." | Reddit — blocked, never revisited | No |
| `ocolakoglu/PetoiBittleChatGPT` + Petoi's official ChatGPT blog post | `Text2SpeechEn.py` fetched directly (2026-09-29, researching voice output) | Yes |
| FinoBot (Bittle X + Pi + ROS2, person-following) | Petoi blog post fetched directly | Yes |

---

## Finding 1 — Confirmed servo-speed sim/real mismatch (highest priority)

BittleJuice measured G2-class servos directly: **step response τ = 33 ms,
speed ceiling ≈ 137°/s**. Measured against our own trained policy directly
(`servo_saturation_check.py`, built 2026-09-24, reproduces
`opencat_gym_env.py`'s exact residual-mode target computation — an earlier
back-of-envelope estimate using `STEP_ANGLE`/`maxJointVelocity` was wrong,
those aren't what actually drives the deployed residual-mode policy):
against `base1_20m`, mean commanded joint speed is **98.9°/s**, p95
**261.2°/s**, max **514.3°/s**, and **26.33% of all joint-step commands
exceed** the assumed 137°/s ceiling. This is a real, measured number, not a
guess — though it's still measured against *BittleJuice's* servo, not G2's
own (pending H13).

BittleJuice's own docs name the trap directly: *"The filter and the
actuator have to be fitted together, or the same lag gets counted twice."*
Our `firmware_model.py` already models the **firmware's own software ramp**
(the `i` command's cosine-eased interpolation, ~250°/s) as if each
interpolated waypoint is instantly achieved — it does not separately model
**physical servo lag on top of that**. If real servos can't track even the
firmware's own ramp, we're currently *under*-counting lag, not
double-counting it — but we don't know, because we've never measured G2's
actual servos.

They also ship a concrete methodology worth copying: `tools/mj_deployability.py`
checks what fraction of a trained policy's commanded joint deltas would
saturate the servo's real speed ceiling, gated at a 15% threshold (their
shipped policy: 2.6%). This is exactly what `servo_saturation_check.py`
above does for us now.

## Finding 1b — Confirmed: URDF joint limits are too narrow for real `rc`

Separate from the speed question above — this is about *range*, not *rate*.
**Confirmed directly (2026-09-24), not just corroborated.**
`reference_gait/rc_ref.npy` is already in the same radian convention as
`models/bittle_esp32.urdf` (its −3.07..3.49 rad range matches
`petoi-firmware-reference.md`'s documented "knees to 200°, shoulders to
−176°" exactly). Compared against the URDF's own limits (±1.57 rad / ±90°
general, 2.00 rad / 114.6° for hips):
- **Shoulders** swing from **−176° to +36°** — the URDF caps these at ±90°.
  Massively outside range.
- **Rear hips** swing from **30° to 200°** — the URDF's own extended hip
  limit only reaches 114.6°. Also massively outside range.
- **Knees** mostly stay within roughly −70° to +100° — close to or just
  slightly past ±90°, not dramatically outside.

So it's specifically the shoulder and hip joints where the real `rc`
self-right skill commands motion the sim is physically incapable of
representing — the URDF's joint limits fully explain why `getup-sim-replay.md`'s
"0/2 recovered" result came back negative, independent of every other
approximation already documented there (open-loop, no IMU-triggered waits,
decoded keyframes). This also independently corroborates
`docs/rl/reference-frames/README.md` (climb work, 2026-09-19, unrelated
investigation): *"our sim's front knee ends up near its 90° physical
limit"* during climbing — the same ceiling binding in a different context.

## Finding 2 — Firmware fork: a real, working alternative to our workarounds

BittleJuice's patched OpenCat fork cuts command→motion latency 198ms→54ms
and raises IMU streaming 5Hz→250Hz, off at boot by default (a flashed robot
behaves exactly like stock until something explicitly requests the realtime
mode). We spent much of this campaign building **workarounds** for exactly
these two stock-firmware limits (`IMU_HOLD_STEPS`, `IMU_RATE_ZERO`,
`CMD_PATH`'s whole timing model in `firmware_model.py`) rather than fixing
them at the source, per an explicit 2026-09-10 decision
(`project_no_firmware_fork` memory) to stay an app layer on stock firmware.
This project demonstrates that decision has a real, working alternative —
not a reason to reverse the decision on its own, but a data point that
should be in the room next time firmware-fork is discussed.

## Finding 3 — Joint-position feedback design: independent convergent confirmation

Both BittleJuice and TypeFly's Petoi wrapper are shaped by the same hardware
fact we already know (`petoi-firmware-reference.md`): the firmware can't
give a fast real joint-position read. BittleJuice's solution — track
commanded state internally, never poll real joint position mid-loop — is
**exactly what `pi_pipeline/gait/run_gait.py` already does**
(`pol.step(quat, gyro)` never re-reads joint position; only IMU feeds every
step, joint state is seeded once at `reset()`). No action needed — this is
reassurance that our design converged on the right answer independently,
not a new idea to adopt.

## Finding 4 — Gyro/angular-rate: external confirmation, not new information

BittleJuice: *"There's no raw gyro. Angular rates are finite-differenced
from the fused attitude stream."* Matches our own 2026-09-22/23 finding
exactly (`G2E_IMU_RATE_ZERO`, "stream has no gyro"). Independent
confirmation from a second project measuring the same firmware family.

## Finding 5 — bittle-mujoco: mass/CoM placement, contact solver tuning

Already surfaced and logged earlier this session
(`docs/project-plan.md`'s fall-recovery TODO): measured real component
masses (273.5g vs Petoi's 265–290g spec), found battery/CoM *position* (not
just inertia) measurably affects trot stability and sim-to-real transfer —
same general bug class as our own zero-inertia payload discovery this
session, different mechanism. Also: their contact-solver tuning (Newton
solver, elliptic cones, `impratio=100`) cut foot slip ~13% — not directly
portable (different physics engine, PyBullet doesn't expose the same
knobs), but a reminder that "foot slip looks visually off" can be a solver
artifact, not just a friction-coefficient question, if we ever chase that
kind of issue again.

## Finding 6 — MH-FLOCKE: a fundamentally different technique, not directly portable

535-neuron Izhikevich spiking network + CPG + reward-modulated STDP + a
small cerebellar model, trained with **no external reward at all** — only
an intrinsic signal (falling = bad, moving = good). 50,000 MuJoCo steps,
zero unrecovered falls, a CPG-weight handoff from ~90% to ~40% as the
spiking network takes over, and a "motor babbling" exploration phase before
real learning starts (loosely parallel to our own curriculum-staging
discussion this session — start easy/passable before hard skills). This is
a different enough architecture (SNN vs. PPO, intrinsic-only vs. engineered
reward shaping) that adopting the technique wholesale isn't realistic — but
it's a useful existence proof that *reward-shaping complexity itself* isn't
the only path to a stable gait, worth keeping in mind if our own reward
audit this session turns out not to be the end of that story.

## Finding 7 — TypeFly: LLM robot control, with a real Petoi/OpenCatESP32 integration

Natural-language → GPT-generated small Python program built from registered
"skills," grounded by a YOLO vision service over gRPC. Directly supports
Petoi Bittle/Nybble/Cub over OpenCatESP32's **HTTP JSON API on port 80** — a
control channel that exists on our own firmware but that `pi_pipeline` has
never used (we're serial-only). Their vision approach is a separate
ESP32-CAM streaming MJPEG to an external YOLO service, architecturally
different from our on-device Grove Vision AI V2 detection. No explicit
safety mechanisms are documented in their design — a contrast point,
not a model to follow, given how much of `pi_pipeline`'s design (feature
flags, halt/release, bench mode) is specifically about *not* doing that. The
skill-registration pattern itself (a name → Python callable, LLM composes
programs from the registry) is structurally the same shape as our own
`voice/skills.py` `SKILLS` dict — convergent design again, not a new idea.

---

## Incorporation plan

Ranked by what's actually actionable and when, not by how interesting each
finding is.

### Do now (pre-hardware, no new scope beyond a diagnostic)
1. **DONE (2026-09-24) — joint limits widened and verified inert for walking
   (Finding 1b).** `models/bittle_esp32.urdf` updated: only the 5 limit
   values `rc_ref.npy` actually violates were touched (`shoulder_left`/
   `shoulder_right` lower −1.57→−3.15 rad, `hip_right`/`hip_left` upper
   2.00→3.55 rad, `knee_left` upper 1.57→1.80 rad) — everything else left
   exactly as-is, since it already covered `rc_ref.npy`'s real range.
   Smoke-tested on `base2_20m`'s live checkpoint (T1.1, T4.2, T8.1, old vs
   new URDF, same seeds): **fall rates and speeds identical to 4 decimal
   places on every cell** — confirms the structural argument (residual-mode
   walking targets, `ref ± 30°`, never approach even the old tighter
   limits) with real measurement, not just reasoning. Applied directly to
   the live `base2_20m` run without a restart (`p.loadURDF()` reloads from
   disk every episode reset, so this took effect on the next reset,
   zero-downtime) — justified specifically because the smoke test showed
   zero effect, unlike the servo-speed fix which had a demonstrated real
   impact and got a full stop-and-restart. Get-up/`rc` sim work can now be
   revisited without the range mismatch as a confound, whenever that
   workstream is picked back up (still not in scope for the current
   campaign).
2. **DONE (2026-09-24) — servo speed saturation (Finding 1).** Built
   `servo_saturation_check.py` and ran it against `base1_20m`: 26.33% of
   commanded joint-steps exceed an assumed 137°/s ceiling (mean 98.9°/s,
   p95 261.2°/s, max 514.3°/s). A real measured number now, not the earlier
   wrong back-of-envelope guess — still pending G2's own measured ceiling
   to know if 137°/s is even the right number to gate against (H13).

### Hardware-gated (needs a real G2 to measure against)
3. **Characterize G2's actual servo step response** (τ, speed ceiling) once
   hardware arrives, the same way BittleJuice's `deploy/bittle_io/`
   measurement suite does — servo type may differ (alloy vs. plastic gears
   per both BittleJuice's and bittle-mujoco's explicit caveats that this
   changes the numbers), so their 33ms/137°/s can't be assumed for G2
   without checking. Add to `docs/rl/hardware-gated-backlog.md` as a new
   H-item once this doc is reviewed.
4. **If #3 shows a real mismatch**, model servo response lag properly (fit
   filter + actuator together, per their explicit warning against
   double-counting) rather than just clamping velocity — this needs real
   measurement data to fit against, so it can't happen before hardware.

### Strategic / needs your explicit decision, not mine to make
5. **Firmware-fork reconsideration.** Not urgent, not something I'd raise
   again without you bringing it up, but the option is now demonstrated
   working elsewhere with concrete wins (54ms vs our ~198ms-modeled stock
   latency, 250Hz vs our accepted 5Hz IMU) against an explicit standing
   decision not to fork. Worth one deliberate conversation at some point,
   ideally after hardware arrives and we know what our workarounds actually
   cost us in practice.
6. **HTTP JSON API as a supplementary control channel** (TypeFly's finding)
   — not something to switch to, `pi_pipeline`'s whole architecture is
   built around serial, but worth knowing it exists on stock firmware in
   case a future tool (external diagnostics, a non-Pi client) wants a
   simpler integration path than serial.

### Noted, no action planned
- MH-FLOCKE's SNN/intrinsic-reward technique — architecturally too
  different to adopt piecemeal; logged as a reference point, not a
  direction.
- bittle-mujoco's contact-solver tuning — PyBullet doesn't expose the same
  knobs; noted as a reminder that "looks slippery" can be a solver
  artifact, not always a friction-coefficient question.
- TypeFly's lack of documented safety mechanisms — contrast, not a model.

## Finding 7 — nobody has actually gotten LLM speech to play through Bittle's own body (researched 2026-09-29)

Prompted by hitting this directly: `pi_pipeline`'s Claude conversation loop
works end-to-end (real API calls confirmed live, see `hw1-log`-adjacent
session notes), but its spoken replies (Piper/`say`) only play through
whichever computer is running the process — there's no speaker wired to
the Pi yet, and BiBoard's onboard speaker turns out not to be usable for
this at all.

**Why BiBoard's speaker is a dead end for this**: its only serial
interface is `T_BEEP` (`b<tone> <ms> ...`, `OpenCat.h`) — a buzzer-melody
format (tone-index + duration pairs), not an audio-playback channel. The
onboard voice module's own spoken replies are canned firmware phrase
banks (English/Chinese), not something arbitrary text can be routed into.
There is no serial command anywhere in `PetoiCamp/OpenCatEsp32` that
accepts a WAV/PCM stream for BiBoard to play back.

**Checked whether anyone else solved this — no one has, as far as public
projects show:**
- Petoi's own official example, ["Talk to Bittle Robot Dog with
  ChatGPT"](https://www.petoi.com/blogs/blog/talk-to-bittle-robot-dog-with-chatgpt),
  links to [`ocolakoglu/PetoiBittleChatGPT`](https://github.com/ocolakoglu/PetoiBittleChatGPT).
  Read `Text2SpeechEn.py` directly: it calls Google Cloud TTS, decodes the
  MP3 response, and plays it with `pydub`'s `play(sound)` — straight to
  whatever computer is running the script's own sound device. Same
  architecture as our `MacTTS`/`--tts mac` test, not routed through Bittle
  at all; the "robot talking" in the demo videos is audio from a nearby
  laptop.
- [FinoBot](https://www.petoi.com/blogs/blog/finobot-ai-robot-dog-bittle-x-follows-someone)
  (Bittle X + Pi + ROS2, person-following) adds a Pi mic for voice *input*
  but documents no speaker or audio-output hardware at all — voice-in
  only, no spoken replies.
- Petoi's own upcoming **Quaddle** robot (successor product, per its
  2026-09 announcement) ships with an *optional second ESP32-S3 "AI core"
  board*, separate from its motion controller, specifically to handle
  voice/LLM features — i.e., Petoi's own hardware team concluded the main
  motion board isn't sufficient for this and built a dedicated second
  board for it. Confirms the constraint is structural, not a `pi_pipeline`
  gap to code around.
- A related firmware thread: a 2026-07 `OpenCatEsp32` commit
  (`f93cdbf`, "Echo motion completion tokens to Xiaozhi voice UART") adds
  a one-byte echo of motion-complete tokens onto `SERIAL_VOICE` — the
  *same* UART already used for the onboard voice module, gated on
  `moduleActivatedQ[1]` (the Voice module flag). This suggests Petoi is
  positioning the onboard voice-module slot as pairable with
  [`xiaozhi-esp32`](https://github.com/78/xiaozhi-esp32) (a real
  open-source ASR+LLM+TTS ESP32 project with its own mic/speaker) as a
  firmware swap on that daughterboard — worth a closer look later if a
  from-scratch voice-hardware rebuild is ever on the table, since it could
  put speech *before* the serial link rather than needing the Pi at all.
  Not pursued now — no confirmed reports of anyone actually doing this on
  Bittle specifically, and it would mean reflashing that sub-board with
  third-party firmware, a bigger step than this project's stock-firmware
  convention.

**Conclusion — the gap is real, not a missed config.** Getting Claude's
actual voice out of G2's own body needs a real speaker wired to the Pi
(a cheap USB speaker, or an I2S amp+speaker breakout like a MAX98357,
are the standard low-cost options for a Pi Zero — not researched in
depth here, just the general Pi-audio pattern) — there's no shortcut
through BiBoard's existing hardware. Logged as an open bring-up gap, not
solved by any known community project.
