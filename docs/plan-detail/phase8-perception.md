# Phase 8 — Environment perception (detail)

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> Phase 8. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## Phase 8 — Environment perception

### Target capability — the near-term goal once vision is working

The concrete definition of done for perception-driven locomotion (the bullet
below on revisiting the gait policy):

> G2 walks confidently across a cluttered floor, steps over cables and small
> objects it sees, slows or stops at a big obstacle or a table edge, and stumbles
> noticeably less.

Explicitly **not** in scope: parkour, recovering from a hard kick or shove,
reliable stair climbing. Those are bounded by the hardware (weak sagittal-plane
servos, no roll-axis joint, a detection — not depth — camera at head height) and
by the reactive-recovery ceiling established in Runs 6–7.

> **2026-09-15 — climbing a single ledge, confirmed need.** Not the "reliable
> stair climbing" scope-out above — a discrete climb-over-one-ledge skill
> (B13/H7), decided needed rather than deferred. Phase F (2026-09-08) tried it
> in sim and hit a wall (`cmh` keyframe + 6 scripted-base designs + from-scratch
> RL all failed to clear a ≥ 2.5 cm ledge in PyBullet) — diagnosed as a
> sim-fidelity limit on contact/grip physics, not proof the real robot can't do
> it. On-hardware plan: port `cmh` and hand-tune first (cheap, answers the real
> question sim couldn't), then explore a `cmh`-anchored learned residual for
> generalization across ledge scenarios. Triggered by vision skill-switching
> (Phase E's `SkillSwitch`/`GaitSelector`, already sim-validated, shelved only
> for lack of a sensor) — a second reason to solve the forward-sensor gap,
> without reopening the separately-closed question of vision *inside* the
> continuous walk policy. Details: [`docs/rl/hardware-gated-backlog.md`](../rl/hardware-gated-backlog.md),
> [`docs/behavior-ideas.md`](../behavior-ideas.md) B13.
>
> **2026-09-19 — sim-fidelity wall closed; a real crawl-climb controller
> works in sim.** The "sim couldn't clear a ledge" finding above was a gap
> in the sim setup, not the simulator itself: the front leg's own 2-DOF
> reach-vs-depth limit was the real blocker, and a validated foot-probing
> skill (joint-tracking-error contact sensing) worked around it. Built
> `rl_training/opencat-gym/crawl_climb.py`: probe-verified front-foot
> placement, a front-pull + tuck-swing-extend rear-leg motion (closely
> matching the official reference climb's own mechanics — reach far,
> stand tall for leverage, plant one rear leg via the same probe-and-search
> mechanism once close enough, advance the same-side front leg), which gets
> all four paws reliably onto a raised ledge without the earlier "jump"
> (explosive tail push) the mechanism depended on before. Full log:
> [`docs/rl/crawl-climb-session-checkpoint.md`](../rl/crawl-climb-session-checkpoint.md).
> One open problem remaining (front legs collapse into an unstable, tilted
> crouch once both rear legs plant, root cause diagnosed but not yet fixed
> cleanly — same doc). **Once that's resolved and the climb is reliable on
> its own terms, the next goal is robustness**: test the same mechanism
> across a range of slightly different situations (ledge height, approach
> angle/distance, starting position, seed/DR variation) rather than just
> the single tuned scenario validated so far — this is the actual bar for
> calling B13/H7 sim-validated, not just "works once, tuned to one case."
> Still sim-only; on-hardware `cmh` port is unblocked by this but not yet
> started.

**Status:** `pi_pipeline/vision/` is scaffolded and testable against a mock
detection feed — same mock-interface pattern as voice/memory. `DetectionFeed`
(`MockDetectionFeed` / `SerialDetectionFeed`), a local `Avoider` reflex
(debounced, urgent hazards preempt the cooldown; `none → turn → stop → back up`),
and `scene.summarize` / `scene.narrate` (LLM-injected, decoupled from `voice`).
Remaining items are the serial wire format, a trained detection model, threshold
tuning, and the Phase 10 wiring — all hardware-gated.

> **2026-09-08 — vision-navigation is flag-gated OFF.** The camera now runs a
> working **3-class detection model** (household member + `dog` + `cat`,
> 2026-09-09) — but that's *recognition*, still not an obstacle/edge detector,
> so nothing on the bot perceives objects in its path and the gate stays on.
> Master flag **`features.vision`** (default
> `False`) forces `vision_safety` / `vision_perception` / `avoidance_act` /
> `explore` off; `BehaviorDriver(vision_available=False)` drops EXPLORE,
> recognition hop, CliffGuard reflex and "G2 meet X" enrollment;
> `run_gait.py --skills` refuses without it. Re-enable the whole stack with
> `G2_FEATURES="+vision"` once a real detector is deployed. Nothing deleted.
> Rationale + the multi-class model options: `docs/vision/detection-layer.md`.

- **Hardware constraint:** Bittle X has one module slot, taken by the AI Vision
  Camera. A separate proximity/distance sensor is not an option alongside it — so
  cliff/edge detection, if pursued, must be a camera-based visual classifier
  (SenseCraft-trained "floor" vs. "edge ahead"), not a dedicated sensor. Use the
  module's `classes()` output for that — a boxless classification path, lighter
  than object detection.
- **Vision module limits** (vendor docs — full detail in
  [`docs/hardware/specs.md`](../hardware/specs.md)):
  - **Detections *or* a raw frame, never both at once.** The `Avoider` reflex
    (needs the detection stream) and `scene.narrate` (needs a frame for Claude)
    must timeshare or mode-switch, not run concurrently. Results and frames use
    different links (UART vs USB), which helps.
  - Model input is **192 × 192**; object detection runs **~10–30 FPS**. Thin
    objects (cables) are only detectable when close/large in frame. A
    vision-conditioned gait policy gets a fresh obstacle read only every ~3–8
    control steps — assume stale-between-frames data.
  - Swapping the deployed model takes **1–2 min** — one multi-class model, no
    runtime switching.
  - Camera-mode toggle over serial is `XC` on / `Xc` off (distinct from `XS`).
- [x] **Obstacle-avoidance reflex** — `vision/avoidance.py`. Local, no network;
      box `area` as the closeness proxy, bearing from `center_x`; consecutive-
      frame debounce + cooldown, with `STOP`/`BACK_UP` preempting. Thresholds
      (`AvoiderConfig`) need tuning against real detections + the robot's
      stopping distance.
- [x] **Camera→Pi serial format confirmed** (SSCMA AT protocol): JSON lines,
      921600 baud, `{"name":"INVOKE","data":{"boxes":[[x,y,w,h,score,target_id]]}}`
      — box centre + size in model-input pixels, score 0–100, numeric class id
      (labels set out-of-band via `VISION_LABELS`). `SerialDetectionFeed` parses
      it; `Detection.from_center_px()` normalises. Link is **USB** (module USB-C
      → Pi USB data port, `/dev/ttyACM0`), not the Grove connector — that's I²C
      (`0x62`), not UART. **Verified on real hardware 2026-09-05**: box `(x,y)`
      IS the centre (`from_center_px` correct as-is), input size IS 240 px
      (`resolution` field says so). `feed.py` fixed to send `AT+INVOKE=-1,0,1`
      on open (module doesn't self-stream) and `AT+BREAK` on close; only
      `type==1` messages carry results.
- [x] **First custom model trained + deployed + pipeline-validated (2026-09-06):**
      a single-class face detector (B15, one household member). SenseCraft "Image
      Collection Training" → Grove Vision AI V2. 161 daylight positive frames + 12
      empty-room negatives (added with **no box** — that's how the flow learns the
      negative class). Positives-only first cut over-fired confidently on a bare
      wall; the negatives killed it. Runs through `g2vision` (`SerialDetectionFeed`
      → `scene` → `Avoider`), acquires/drops the subject instantly, scores ~60–80.
      Wired into `.env` (`VISION_LABELS` / `VISION_MIN_SCORE=45`). Full workflow:
      `docs/guides/train-vision-model.md`.
- [x] **Multi-class detection model WORKING on device (2026-09-09):** 3 classes
      (household member + `dog` + `cat`), YOLOv8n @ 192 px, mAP@50 0.907. Root
      cause of a week of dead flashes: the GV2 firmware is **frozen at Jan 2025**
      and only decodes ~2024-era export heads. The path that works —
      `ultralytics==8.2.8` trained on Colab, then `yolo export format=tflite
      int8` run **locally on arm64 Python 3.9** (Colab's 3.13 can't), then vela.
      All of it is repo tooling now: **`tools/gv2/`**
      (`split_yolo_dataset.py`, `export_yolov8_gv2.sh`, `vela_config_we2.ini`) +
      `tools/autobox_coco.py` + `tools/vision_diag.py`. Full 12-step process:
      `docs/vision/custom-model-recipe.md`. Known limit of this first
      model: detects up close only (100-image INT8 calib set; 300+ wanted) —
      improvement loop speced in `docs/vision/capture-progress.md`.
- [ ] **Improve the 3-class model** — diagnostic `vision_diag` logging pass →
      shot list → recapture (distance/pose variety) → retrain with a 300+
      calibration set. Then add a 4th class (2nd household member) at `nc: 4`.
- [ ] Train the **obstacle / table-edge** classes (cables, small objects, desk
      edge) — the desk-edge class is `CliffGuard`'s detector and is gated on the
      camera being **mounted on the frame** (real POV; hand-held frames won't
      transfer). See B16.
- [ ] **Cliff/edge avoidance — `CliffGuard`, designed 2026-09-04, HIGHEST
      PRIORITY once the camera lands** (G2 lives on the user's desk; must never
      walk off it). Full design: `docs/behavior-ideas.md` **B16**. Confirmed not
      trainable into the gait (no forward perception, no real foot-force
      sensing either) — a zero-debounce local reflex that preempts every other
      behavior, using the light `classes()` floor-vs-edge path, custom-trained
      on the real desk, biased hard toward false-stops over a missed edge.
      **Behavior-audit finding, 2026-09-16:** on top of needing the trained
      desk-edge classifier + mounted camera, the wiring itself is incomplete —
      `app/__main__.py`'s `_build_runtime()` never constructs a `CliffGuard` or
      passes `cliff=` to `BehaviorDriver`, so the reflex has zero live effect
      even once those land. Needs both the classifier work and the wiring,
      not just one.
      Physical backstop (a desk-edge lip, supervision-gated autonomy) is the
      honest answer for a true "never," since vision alone can't promise it.
- [x] **Scene description path** — `vision/scene.py`: `summarize()` (deterministic
      text from detections) and `narrate(frame, ask)` where `ask` is an injected
      `str -> str` (the voice layer's Claude call, or a dedicated one). Structured
      detections → text → Claude → spoken, no raw frames.
- [ ] "Reasoning" about what it sees: BiBoard V1's ESP32-U4WDH can't run a vision-
      language model, so send structured detections (type/position) over serial to
      the Pi and hand descriptions to Claude — no raw frames.
  - pidog-embodiment's Pi 4 benchmarks for on-device VLM (SmolVLM): 27–37 s per
    call, ~400 MB RAM — borderline on a Pi 4, infeasible on a Pi Zero 2 WH.
    Confirms cloud reasoning is the right call.
  - PiDog attaches images to LLM calls only for occasional "what do you see"
    queries, not continuous avoidance — matches the split above.
- [~] **Perception-in-the-loop locomotion — RL approach CLOSED 2026-09-07; now a
      behaviour-layer reflex.** A 3-campaign autonomous investigation
      (`docs/rl/vision-in-gait.md`) tried to bake a
      forward-terrain feature + goal-bearing command + cliff feature into the
      gait policy so it could slow / step-over / detour / halt from vision.
      **Result: goal-directed turning is not achievable in this sim** — an
      open-loop test showed the firmware scripted turn gaits (`wkL`/`wkR`)
      produce ~0° of yaw in PyBullet with this URDF (real Bittle turning leans on
      foot-slip + the firmware gyro turn-assist the sim doesn't model). No 20M
      ever ran; `run20m_ppo` untouched.
      **New plan:**
      - **Turning → firmware.** Heading changes use the scripted `kbk`/`wkL`
        turn gaits (they work on the real robot), triggered by the behaviour
        layer. `AvoidanceAction.TURN_*` map to these.
      - **Vision-while-walking → the `Avoider` reflex** (`pi_pipeline/vision/
        avoidance.py`), which sets the *speed command* the RL walk policy already
        tracks. Added 2026-09-07: `AvoidanceAction.SLOW` (obstacle ahead but not
        near → `ACTION_SPEED_SCALE` 0.4) for anticipatory slowing. Sequence as an
        obstacle nears: NONE → SLOW → STOP / BACK_UP (dead ahead) or TURN
        (firmware, to a side). Calibrate the area→speed thresholds on hardware.
      - **Cliff/edge stop** — the `CLIFF` sim feature is built; the real-robot
        path needs the vision model trained to detect a desk edge (hardware-
        gated). Until then `CliffGuard` stays a hard reflex spec (B16).
      - **Tier B (a fresh vision-baked ~20M) is reserved** for *if* hardware
        shows the command-level reflex isn't fine enough — i.e. the robot still
        clips cables it can see, or the decel is too abrupt (within-stride,
        sub-command-timescale things a speed command can't express). Not
        justified pre-hardware: the obstacle-reward package measured ~neutral in
        isolation (Phase 0), and **Phase D (2026-09-08) confirmed it directly** —
        a from-scratch 20M with the terrain feature in the observation was no
        more capable than an identical blind 20M (same 0% falls, less obstacle
        anticipation, no regression). Vision-in-the-loop ruled out; the `Avoider`
        speed reflex is the path. Report:
        `claude.ai/code/artifact/bfb58d90-71ca-4681-9c72-d14e15e56b7a`.
      - Built + kept dormant for a future Tier B run: `G2E_TERRAIN_FEATURE` /
        `GOAL_MODE` / `CLIFF` / `TURN_BLEND`, `run20m_graft28x`, `benchmark_goal.py`.
      - **Phase E (2026-09-08) — vision picks a SCRIPTED skill on the frozen
        walk. IMPLEMENTED, hardware-gated.** No training: `run20m_ppo` stays
        frozen; a vision reading selects a `GaitMode` (cruise / careful /
        step-over / back-out / brace / inspect / halt) and `SkillSwitch` plays a
        scripted OpenCat keyframe with a phase-gated via-stance blend. Sim
        results (0 training): +48% through low obstacles (step-over attributed),
        0% vs 34% edge-falls with `CliffGuard`. `smoke_vfix3` (a fresh 3M
        vision-conditioned run with the Phase D fixes) confirmed learned
        vision-in-the-policy is a dead end a second way (it stalls). next-1..5
        done: high-step A/B (trot kept), `INSPECT` + near blind zone, per-ray
        slope grounding, `BRACE`, deployment wiring. Stack:
        `pi_pipeline/gait/skill_layer.py` (`SkillLayer` = `GaitSelector` +
        `SkillSwitch` + `CliffGuard`), `run_gait.py --skills` (serial Grove
        Vision AI feed or mock). Walk-around maneuver **can't be scripted** —
        no lateral leg DOF; a detour needs a firmware turn (nav-layer decision).
        Report: `claude.ai/code/artifact/88ea1a14-ab32-4000-8e87-422264667150`.
        Plan: `docs/rl/vision-in-gait.md` (`>>> RESUME (Phase E)`).
        The adapter skill probe (`docs/rl/adapter-skill-probe-spec.md`)
        stays the route for *one* genuinely-learned skill if a scripted one
        proves too fragile on hardware.

      --- superseded plan (2026-09-03), kept for context ---
      The current gait is reactive and IMU-only, so it can't anticipate terrain
      or deliberately step around an obstacle — it only learns a lip exists
      *after* a foot hits it (2026-09-03 probe batch: never falls but *stalls*
      against curbs / lips / on carpet, blind forward).

      **DECIDED ARCHITECTURE (2026-09-03) — NOT ADOPTED:** the walk policy gets **its own
      low-bandwidth forward terrain feature, fed directly into its 278-d
      observation at control rate**, *separate from* the vision→Claude /
      vision→`Avoider` command-setting path. Not "vision biases the command" —
      that keeps the policy blind and caps it at "creep on command"; Claude is
      also far too slow (seconds/call) for foot-placement timescale. Instead:
      - An **on-Pi module** turns the camera's detection stream into a compact
        feature and appends it to the policy observation. **Frozen layout** (4
        floats, `[-1,1]`), refreshed at detection rate (~10–30 Hz), held stale
        between frames:
        `[ present, dist_norm, bearing_norm, tall_flag ]` —
        seen-or-not, distance/range, angle-off-heading/half-FOV, and
        low-enough-to-step vs go-around/stop.
        Sim generator: `opencat_gym_env._scan_terrain` (a forward ray fan, gated
        by `TERRAIN_FEATURE`, off by default so `run20m_ppo` is unaffected).
        Pi generator: `pi_pipeline/vision/terrain_feature.py` (`terrain_feature()`
        + `TerrainFeatureExtractor`), from the detection `Frame`. **Both ends
        must stay in sync** — the plumbing (both sides + tests) landed
        2026-09-03; the constants get calibrated on hardware.
      - Claude stays *above* this loop (navigation goals, narration); the
        `Avoider` reflex may still set coarse speed/yaw commands in parallel.
        The terrain feature and the command path are independent inputs.
      - **Sim training:** synthesize that same feature from PyBullet ground-truth
        obstacle geometry, with realistic detector noise / miss-rate / latency
        (tuned to the real model's measured stats, `sysid`-style), add it to the
        observation, and retrain. **Claude does not need to be in the sim** — it
        isn't in this loop; the loop is camera→feature→policy, all Pi-local, and
        Claude's high-level commands are already covered by the sim's command
        randomisation.
      - Expected payoff: anticipatory slowing / go-around / stop for *large*
        obstacles and curbs (camera + detector are good at these). Fine
        foot-placement over a 12–15 mm lip stays marginal — head-height forward
        camera + 192×192 detector is weak on small low-contrast terrain edges.
      - The **"don't stall" reward idea** (dense forward-progress term + sparse
        breakthrough bonus, `robustness-backlog.md` R-NOSTALL) is **deferred to
        here** — it only makes sense once the policy can see far enough ahead to
        slow *before* contact; on the blind policy it just produces frantic
        scrabbling, not intentional stepping.

      Only possible once perception exists; a distinct effort from the
      flat-ground gait.
- [ ] (Stretch, with vision + IMU in place) More robust self-righting — flip
      detection from the IMU plus a dedicated recovery policy (or the firmware
      skill for the cases it covers, a learned fallback for the rest). Ruled out
      as a pure reward-shaping target in Run 7; becomes incremental once the IMU
      is already feeding the policy. See
      [`docs/hardware/self-righting.md`](../hardware/self-righting.md).
