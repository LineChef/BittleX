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
- Whether Bittle X's board can reliably power the Pi Zero 2 W long-term, or whether the Pi should be powered independently even when mounted
- Whether the back cover/lid can close with the Pi installed, or whether it stays exposed (based on older Bittle docs and builder photos, expect it to stay exposed)
- No confirmed pre-made enclosure exists yet for Pi-on-Bittle-X — may need custom 3D-printed cover (check r/petoi and github.com/PetoiCamp/NonCodeFiles for community designs before creating one from scratch)
- Which exact ESP32 chip variant ships on Bittle X V2's BiBoard (affects whether raw camera images can stream to the Pi, vs. only on-device detection results)

---

## Phase 1: GitHub Repo Setup
- [ ] Create a repo for the project (decide structure: single repo for everything, or split — e.g., one for RL training code, one for the Pi-side voice/memory pipeline)
- [ ] Add a starter README — project goals, hardware plan, this roadmap
- [ ] Set up a `.gitignore` from the start (exclude API keys/secrets, large trained model files if not meant to be versioned, virtual environment folders)
- [ ] Decide where secrets will live (environment variables or a local gitignored config file — never commit credentials)
- [ ] Commit incrementally as each phase progresses, not in one big dump at the end — gives you real history, and doubles as portfolio material later

## Phase 2: Orientation (while hardware ships / before touching real robot)
- [x] Try the community Bittle simulator (grgv.xyz/blog/bittle) to get a feel for movement/gait
- [ ] Check Petoi's official browser simulator (via bittle-x.petoi.com docs)
- [ ] Browse the OpenCat GitHub repo (github.com/PetoiCamp/OpenCat) to see how movements/gaits are structured in code
- [ ] Try Petoi's free beginner coding curriculum (C++ and/or block-based Petoi Coding Blocks)
- [ ] Get basic Python fundamentals down (variables, functions, loops, classes) — translating existing JS/CSS/HTML logic skills, not starting from zero conceptually

## Phase 3: RL Training — Simulation Only (can run in parallel with hardware arriving/shipping)
*This phase only needs software — no physical robot required until the deployment step in Phase 6.*
- [ ] Set up opencat-gym-sim2real (PyBullet + Stable-Baselines3) in simulation
- [ ] Design and iterate on the reward function (this is the primary lever — expect multiple rounds of tweaking, not a one-shot success)
- [ ] Run automated training (unattended, potentially hours/days) and monitor the reward curve for improvement/plateau
- [ ] Evaluate the trained policy in simulation and save the best checkpoint(s) for later real-world deployment
- [ ] (Stretch goal, optional) Explore imitation learning approaches referencing the UVA/Harvard Bittle research, given standard servos lack position feedback

## Phase 4: Hardware Assembly
- [ ] Assemble Bittle X V2 (40–90 min per Petoi's estimate)
- [ ] Calibrate joint servos (pre-assembled units are only coarse-tuned out of the box — fine calibration is a required step, not optional)
- [ ] Get it moving via the stock app/firmware first, before touching custom code — confirms hardware works before adding complexity
- [ ] Flash/set up the Raspberry Pi Zero 2 WH:
  - Use Raspberry Pi Imager to pre-configure Wi-Fi + enable SSH before first boot (headless setup — no monitor/HDMI needed)
  - Confirm SSH access from your regular computer
- [ ] Mount the Pi to Bittle X's frame; test power delivery and serial communication between Pi and BiBoard independently (known community issue: power can work while serial communication doesn't)
- [ ] Set up the AI Vision Camera Module: mount at head, connect to Grove socket on BiBoard, upload firmware via Petoi Desktop App or Arduino IDE

## Phase 5: Basic Programming & Control
- [ ] Send basic movement commands to Bittle X via Python (walk, sit, preset behaviors) — establishes the base control layer
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
- [ ] Decide path for "reasoning" about what it sees:
  - If ESP32-S3/C3 confirmed: stream camera frames to Pi → occasionally send to Claude for interpretation
  - If standard ESP32 confirmed: send structured detection results (object type/position) over serial to Pi → hand descriptions to Claude instead of raw images

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

## Community & Support Resources
- r/petoi (Reddit) — Petoi's own recommended community
- Petoi Forum Archive (petoi.camp)
- github.com/PetoiCamp/OpenCat — firmware source
- github.com/PetoiCamp/NonCodeFiles — community 3D-print files/mods
- opencat-gym-sim2real repo — RL training environment

---

*This plan is a living document — update phases, priorities, or specs as we learn more once hardware arrives and testing begins.*
