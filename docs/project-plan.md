# Bittle X Robot Companion — Project Plan

**Goal:** Build a Bittle X quadruped that (1) learns to walk via reinforcement learning rather than scripted movement, (2) perceives its environment via camera and avoids obstacles, (3) holds voice conversations powered by Claude, and (4) develops persistent memory of past interactions over time.

**Background:** Builder has strong HTML/JS/CSS experience, no prior Python. Learning Python itself is low-risk; the real challenges are hardware debugging, RL training, and multi-system integration.

---

## Parts List (Finalized — $567 total)

| Item | Price |
|---|---|
| Petoi Bittle X V2 (alloy servos) | $380 |
| Raspberry Pi Zero 2 WH kit (pre-soldered GPIO headers, heatsink, mini-HDMI adapter, OTG cable) | $115 |
| SanDisk 32GB Ultra microSDHC (A1, Class 10, UHS-I) | $22 |
| 5V/2.5A micro-USB power supply | $10 |
| Petoi AI Vision Camera Module (Grove Vision AI V2, Arm Cortex-M55 + Ethos-U55) | $40 |

**Not yet resolved / to check when hardware arrives:**
- Whether Bittle X's board can reliably power the Pi Zero 2 W long-term, or whether the Pi should be powered independently even when mounted — Petoi's own docs warn that Nybble sees "reduced motion capability" once a Pi draws current from the same battery, so this is a real risk, not just a theoretical one. Budget for possibly powering the Pi independently.
- Petoi's official BiBoard V1 spec (docs.petoi.com/biboard/biboard-v1-guide) lists Pi compatibility as "Raspberry Pi 3A+, 4, 5" — **Pi Zero 2 WH is not explicitly listed.** Verify the 5-pin socket and serial wiring are still compatible when hardware arrives.
- ~~No confirmed pre-made enclosure exists yet for Pi-on-Bittle-X~~ — **resolved:** Petoi provides an official STL for a back cover with a Pi cutout: [`Bittle_Cover_with_hole_for_Pi.stl`](https://github.com/PetoiCamp/NonCodeFiles/blob/master/stl/Bittle%20%26%20BittleX/BittleCover/Bittle_Cover_with_hole_for_Pi.stl) (per docs.petoi.com/apis/raspberry-pi-serial-port-as-an-interfac/for-biboard-v1). This implies the cover *can* close over the Pi, contrary to the original assumption that it'd stay exposed — confirm fit once the Pi is mounted.
- ~~Which exact ESP32 chip variant ships on Bittle X V2's BiBoard~~ — **resolved:** BiBoard V1 uses a standard **ESP32-U4WDH** (Xtensa dual-core LX6, via an ESP32-MINI-1 module) — not an S3/C3. Per Phase 8, this means the vision approach is "send structured detection results over serial to Pi," not raw frame streaming.

---

## Phase 1: GitHub Repo Setup
- [x] Create a repo for the project (decide structure: single repo for everything, or split — e.g., one for RL training code, one for the Pi-side voice/memory pipeline) — complete
- [x] Add a starter README — project goals, hardware plan, this roadmap — complete
- [x] Set up a `.gitignore` from the start (exclude API keys/secrets, large trained model files if not meant to be versioned, virtual environment folders) — complete
- [x] Decide where secrets will live (environment variables or a local gitignored config file — never commit credentials) — complete (documented in `.gitignore`: `.env`, `config.local.*`, `**/secrets.py`, `**/api_keys.py`)
- [ ] Commit incrementally as each phase progresses, not in one big dump at the end — gives you real history, and doubles as portfolio material later (ongoing practice, not a one-time step)

## Phase 2: Orientation (while hardware ships / before touching real robot)
- [x] Try the community Bittle simulator (grgv.xyz/blog/bittle) to get a feel for movement/gait — complete
- [ ] ~~Check Petoi's official browser simulator (via bittle-x.petoi.com docs)~~ — skipped (2026-08-29): searched the full `bittle-x.petoi.com` manual (all 7 chapters + useful links) and the Doc Center's "Supporting Application and Software" page; no official browser-based Bittle X simulator was found. Only found a tutorial for simulating Bittle in **NVIDIA Isaac Sim** (a full robotics simulator — more relevant to Phase 3's RL work than a quick orientation demo) and **OpenCatWeb** (a web UI for controlling a *real*, Pi-mounted robot — not a simulator). Revisit if a tool for this is found later; for now, the community simulator above covers this step.
- [x] Browse the OpenCat GitHub repo (github.com/PetoiCamp/OpenCat) to see how movements/gaits are structured in code — complete. Note: `OpenCat` (AVR/NyBoard) and `OpenCatEsp32` (ESP32/BiBoard — what Bittle X actually runs) share the same gait architecture, so findings apply to our hardware. See "How gaits are structured" note below.
- [ ] Try Petoi's free beginner coding curriculum (C++ and/or block-based Petoi Coding Blocks) — deferred (2026-08-29): decided to jump ahead to Phase 3 rather than gate on this; revisit if desired
- [ ] Get basic Python fundamentals down (variables, functions, loops, classes) — translating existing JS/CSS/HTML logic skills, not starting from zero conceptually — deferred (2026-08-29): will pick this up along the way while building Phase 3 rather than as a prerequisite gate

## Phase 3: RL Training — Simulation Only (can run in parallel with hardware arriving/shipping)
*This phase only needs software — no physical robot required until the deployment step in Phase 6.*
- [x] Set up opencat-gym-sim2real (PyBullet + Stable-Baselines3) in simulation — complete (2026-08-29). Found and confirmed the actual repos:
  - [`github.com/ger01d/opencat-gym`](https://github.com/ger01d/opencat-gym) (MIT license, commit `12b39ff`) — the Phase 3 training environment (PyBullet + Stable-Baselines3 + Gymnasium, `train.py`/`opencat_gym_env.py`). Confirmed it targets our exact hardware: ships `models/bittle_esp32.urdf`. A curated copy (source only, no demo GIFs/pretrained weights) is vendored at `rl_training/opencat-gym/` — see [`rl_training/README.md`](../rl_training/README.md).
  - [`github.com/ger01d/opencat-gym-sim2real`](https://github.com/ger01d/opencat-gym-sim2real) — a separate, related repo for deploying a trained policy to the real robot over serial. That's Phase 6, not this step.
  - **Environment blockers hit and resolved along the way** (kept here in case they recur on another machine):
    - System Python was 3.8.9 (old Xcode-bundled, EOL); Stable-Baselines3/Gymnasium require Python ≥3.10 → installed Python 3.11 via Homebrew, set up a project `.venv` from it.
    - `brew install python@3.11` first failed because Xcode (13.2.1) was too outdated for Homebrew to build against → fixed by `xcode-select --install` (fresh Command Line Tools), then `sudo xcode-select --switch /Library/Developer/CommandLineTools` to point at them instead of the old Xcode.app.
    - `pybullet` has no prebuilt wheel for macOS (only Linux) and fails to compile from source on current macOS SDKs — a decades-old zlib compatibility shim in its bundled zlib copy (`#define fdopen(fd,mode) NULL` on `MACOS`/`TARGET_OS_MAC`) clobbers the real `fdopen` declaration in `_stdio.h`. Fixed with `CPPFLAGS="-Dfdopen=fdopen"` during install (documented in `requirements.txt`).
    - Skipped `stable-baselines3[extra]`'s Atari extras (`ale-py` needs SDL2 dev libraries to build, and we don't need Atari support) — installed plain `stable-baselines3` + `gymnasium` + `tensorboard` instead.
  - Verified working: `opencat_gym_env.py`'s `OpenCatGymEnv` passes Stable-Baselines3's `check_env`, resets, and steps successfully in this environment.
- [ ] Design and iterate on the reward function (this is the primary lever — expect multiple rounds of tweaking, not a one-shot success)
  - Note: real-time terrain/disturbance adaptation is realistic and is the actual advantage of RL over scripted gaits, but Bittle's servos have no torque/force feedback and there's no per-foot contact sensing — the policy's only real-time body-state signal is the onboard IMU (orientation/tilt). So it can learn to recover from pushes, slopes, and minor unevenness, but won't have foot-level terrain awareness like research quadrupeds with force-sensing legs. To get real robustness (not just flat-ground walking), the reward function should explicitly reward balance recovery from perturbation, not just forward velocity — and training should use domain randomization (varied simulated terrain roughness, friction, random pushes) so the policy generalizes to real-world variation it never saw exactly. Feeding vision (Phase 8) into the policy later would push this further (reacting to terrain before it's underfoot) but isn't in the base plan.
- [ ] Run automated training (unattended, potentially hours/days) and monitor the reward curve for improvement/plateau
- [ ] Evaluate the trained policy in simulation and save the best checkpoint(s) for later real-world deployment
- [ ] (Stretch goal, optional) Explore imitation learning approaches referencing the UVA/Harvard Bittle research, given standard servos lack position feedback

## Phase 4: Hardware Assembly
- [ ] Assemble Bittle X V2 (40–90 min per Petoi's estimate)
- [ ] Calibrate joint servos — note: Petoi's own manual (bittle-x.petoi.com/4-calibration) says pre-assembled units "should have been calibrated" and you can skip straight to Play; this contradicts the "fine calibration is required" assumption below. Treat calibration as a check/fine-tune step, not an assumed-required one — only dig in if movement looks off.
- [ ] Get it moving via the stock app/firmware first, before touching custom code — confirms hardware works before adding complexity
- [ ] Flash/set up the Raspberry Pi Zero 2 WH:
  - Use Raspberry Pi Imager to pre-configure Wi-Fi + enable SSH before first boot (headless setup — no monitor/HDMI needed)
  - Confirm SSH access from your regular computer
- [ ] Mount the Pi to Bittle X's frame; test power delivery and serial communication between Pi and BiBoard independently (known community issue: power can work while serial communication doesn't). Concrete steps per Petoi's Raspberry Pi serial docs (docs.petoi.com/apis/raspberry-pi-serial-port-as-an-interfac + its "For BiBoard V1" subpage):
  - Install the 5-pin Pi socket on BiBoard V1 (Petoi's official 3D-printed back cover with a Pi cutout: [`Bittle_Cover_with_hole_for_Pi.stl`](https://github.com/PetoiCamp/NonCodeFiles/blob/master/stl/Bittle%20%26%20BittleX/BittleCover/Bittle_Cover_with_hole_for_Pi.stl))
  - On the Pi: `sudo raspi-config` → Interface Options → Serial Port → disable the login shell over serial, enable the serial port hardware → reboot
  - Also disable the Pi's 1-wire interface (avoids repeated reset signals on GPIO 4 conflicting with the board)
  - On the BiBoard: send serial command `XS` (or modify `OpenCat.h` and reflash) to enable "Serial 2" working mode so it talks to the Pi
  - Serial port device name on Pi: docs say `/dev/ttyS0` for Pi 3/4, `/dev/ttyAMA0` for Pi 5 — Pi Zero 2 W isn't explicitly listed; likely `/dev/ttyS0` given its Pi-3-family SoC, but confirm once wired up
  - Use `ardSerial.py` from the OpenCat repo as the reference Python serial commander (e.g. `./ardSerial.py kcrF` = "perform skill crawl Forward")
- [ ] Set up the AI Vision Camera Module: mount at head, connect to Grove socket on BiBoard, upload firmware via Petoi Desktop App or Arduino IDE

## Phase 5: Basic Programming & Control
- [ ] Send basic movement commands to Bittle X via Python (walk, sit, preset behaviors) — establishes the base control layer. Reference docs: [Python/SerialMaster user guide](https://docs.petoi.com/python/serialmaster-user-guide), [Raspberry Pi serial port as an interface](https://docs.petoi.com/apis/raspberry-pi-serial-port-as-an-interfac)
- [ ] Get comfortable with OpenCat's command structure before building anything on top of it
- [ ] Test the AI Vision Module's on-device detection via the SenseCraft AI Model Assistant web debug GUI

## Phase 6: RL Sim-to-Real Deployment
- [ ] Deploy the trained policy (from Phase 3) to the real Bittle X
- [ ] Expect a real performance gap vs. simulation — this is normal, not failure
- [ ] Iterate: adjust reward function and/or retrain in simulation based on what you observe on real hardware, redeploy

## Phase 7: Voice + Claude Integration
- [ ] Build audio capture pipeline on the Pi (built-in mic on Bittle X's board)
- [ ] Add speech-to-text (decide: cloud API vs. local model like Whisper — affects Pi RAM headroom decisions)
- [ ] Connect to Claude via the Anthropic API (separate billing from Claude Pro subscription — usage-based cost)
- [ ] Add text-to-speech for Claude's responses through the robot's speaker
- [ ] Confirm this runs independently of the built-in 35+ preset voice commands (two separate systems, not in conflict)

## Phase 8: Environment Perception
- [ ] Get real-time obstacle avoidance working using the vision module's on-device inference (local, fast, no Pi/cloud dependency)
- [ ] Path for "reasoning" about what it sees is now decided: BiBoard V1 is confirmed to use a standard **ESP32-U4WDH** (not S3/C3 — see Parts List notes), so send structured detection results (object type/position) over serial to Pi → hand descriptions to Claude instead of raw images. (Raw frame streaming to the Pi is not an option on this hardware.)

## Phase 9: Memory System
- [ ] Design a simple persistent storage layer on the Pi (SQLite or lightweight local vector store) to log conversation history
- [ ] Build retrieval: pull relevant past context into each new conversation's prompt to Claude
- [ ] Keep this as a separate system from movement/vision — not a unified "brain," multiple systems running alongside each other

## Phase 10: Full Integration
- [ ] Get all systems — movement, vision, voice, memory — running alongside each other without conflicts
- [ ] Expect this phase to surface real bugs/timing issues even after each piece worked individually — budget real time for it
- [ ] Update the GitHub README with final setup instructions and a demo (video/gif)
- [ ] Add requirements.txt / dependency list so the setup is reproducible
- [ ] Optional: write up learnings/notes in the repo — useful for your own reference and as portfolio material

---

## Known Risks / Honest Expectations
- Hardware debugging is a different skill than web dev debugging (no console errors — could be code, wiring, power, or hardware itself)
- RL-trained gaits will likely look rougher/janklier than a real animal's, especially at first
- Sim-to-real transfer rarely works perfectly on the first deploy — expect a real gap and iteration
- Full multi-system integration (Phase 10) is realistically the hardest, messiest part — not a clean bolt-together

## Reference Notes: How OpenCat Gaits Are Structured

From browsing `github.com/PetoiCamp/OpenCat` (AVR/NyBoard) and `github.com/PetoiCamp/OpenCatEsp32` (ESP32/BiBoard — the actual Bittle X firmware). Relevant background for Phase 3 (contrast with our RL approach) and Phase 5 (sending commands).

- Every named skill (walk, trot, crawl, sit, push-up, kick, etc.) is a **hand-authored, baked-in keyframe animation** — a compact `const int8_t[] PROGMEM` array of servo angles, one array per skill, stored in flash. `InstinctBittleESP.h` (ESP32/Bittle X) currently defines ~93 of these.
- Two parallel arrays tie it together: `skillNameWithType[]` (e.g. `"wkFI"`, `"trFI"`, `"sitI"` — the trailing `I`/`N` marks "Instinct" (built-in) vs "Newbility" (user-taught, saved to EEPROM)) and `progmemPointer[]` (the matching pointer to each skill's frame array). Sending a serial command like `kwkF` looks up the name and plays back its frames.
- Each array's header row encodes frame count/period and a direction/type flag; a positive period means a **looping gait** (walk, trot — continuously cycled, and blended in real time with IMU/gyro balance correction via `gyroBalanceQ`), while a negative period means a **one-shot behavior** (sit, push-up, scratch — plays through once, and some even wait on a specific IMU trigger angle mid-sequence, e.g. "rock" only advances once pitch crosses a threshold).
- The robot has 16 total servo channels (`DOF 16`): 4 for head/tail/gripper, the other 12 for the legs (8 of which — 2 per leg, shoulder + knee — are `WALKING_DOF`, the joints gait keyframes actually drive).
- **Why this matters for us:** this is the opposite approach from Phase 3's plan — OpenCat's gaits are fixed, hand-tuned animations, not something learned. Our RL-trained policy will need its own runtime path to drive the same 8 walking servos (either bypassing this skill-array system entirely, or injecting learned frames in the same format) rather than picking from `skillNameWithType`.

## Community & Support Resources
- r/petoi (Reddit) — Petoi's own recommended community
- Petoi Forum Archive (petoi.camp)
- github.com/PetoiCamp/OpenCat — firmware source
- github.com/PetoiCamp/NonCodeFiles — community 3D-print files/mods
- opencat-gym-sim2real repo — RL training environment

---

*This plan is a living document — update phases, priorities, or specs as we learn more once hardware arrives and testing begins.*
