# Hardware specs — from vendor docs, gathered before the hardware arrived

Pulled from Petoi's guide/spec pages, the Seeed Grove Vision AI V2 wiki, Raspberry
Pi, and PiSugar. Every "→" line is why it matters to this project. Re-verify the
open items on the bench once the parts are in hand.

---

## BiBoard V1 (the controller in Bittle X V2)

| Spec | Value |
|---|---|
| MCU | ESP32-U4WDH (Xtensa dual-core LX6), via an ESP32-MINI-1 module |
| SRAM / ROM / Flash | 520 KB / 448 KB / **4 MB** |
| IMU | **6-axis MPU6050** (or ICM42670 by availability) — 3-axis gyro + 3-axis accel |
| Servo drive | 12 PWM channels (position PWM) |
| Grove sockets | 4, typed: G1 = UART2, G2 = I²C, G3/G4 = analog in |
| Input / operating voltage | 7–9 V in, 5 V operating, 0.1–0.2 A board draw |
| Radios | Wi-Fi 802.11 b/g/n, Bluetooth 4.2 BR/EDR + BLE |
| Pi port | 5-pin socket, officially "Raspberry Pi 3A+, 4, 5" |
| Extras | onboard **offline voice-recognition module** (bilingual, multi-word), onboard **speaker**, capacitive touch socket, CH343P USB-serial, BOOT/Reset buttons |

- → **The IMU has no magnetometer.** There is no absolute heading reference on the
  real robot — yaw is integrated from the gyro and drifts over
  seconds-to-minutes. The RL sim reads perfect yaw from the base quaternion, so
  any "hold heading to N degrees" objective is optimistic on hardware. Prefer
  penalising/observing **yaw rate** (clean from the gyro) over absolute heading,
  and expect real-world heading hold to be looser than sim.
- → **Flash is 4 MB, SRAM 520 KB.** Older Petoi pages that say "16 MB QSPI flash /
  ESP32-WROOM-32D" describe BiBoard **V0**, not V1. This is a tight budget for the
  "run the gait policy on the MCU instead of the Pi" backlog idea.
- → **Onboard offline voice recognition + speaker already exist.** The Phase 7
  plan routes wake→STT→Claude→TTS through the Pi; the board's own wake-word/command
  recognition is a candidate for the wake trigger or an offline command fallback,
  offloading the Pi.
- → **Only 4 Grove sockets, and they're typed.** The AI Vision module takes one.
  Plan any additional Grove sensors around G1=UART2 / G2=I²C / G3-4=analog.
- → **Servo position feedback: CONFIRMED to exist, but slow — not a control-rate
  signal.** Full write-up below under "Servo position feedback".

## P1S alloy servos (×9: 8 legs + 1 neck)

| Spec | Value |
|---|---|
| Torque | ~3 kg·cm (~0.29 N·m) peak |
| Speed | ~0.07 s / 60° (~14 rad/s no-load) |
| Range | 270° controllable |
| Voltage | 8.4 V compatible |
| Build | coreless motor, alloy gears, ball bearing; "100+ h" life |
| Protection | electronic overheat cutback |

- → Sim uses ~0.2 N·m effective — reasonable vs the 0.29 N·m peak (peak ≠
  continuous).
- → **Overheat protection throttles/cuts hot servos.** Long real-robot RL or eval
  sessions will hit this — build in cooldown breaks.

## Servo position feedback (researched 2026-09-01)

**Confirmed it exists on our hardware.** Petoi added position feedback to servos
manufactured after **March 2024** (all with a label/laser-mark after May 2024,
possibly earlier). It works **only on ESP32 BiBoards** (our BiBoard V1 qualifies),
not NyBoards. Current **Bittle X V2 ships with feedback servos as standard** —
Amazon/eBay/Petoi listings all say "alloy feedback servos" for the V2 alloy
model, which is what we ordered. Petoi *does* also sell a servo set "without
feedback control", so it's not universal across all their SKUs — but the V2 kit
has them. **Still do the 30-second check on arrival:** flash latest firmware,
send serial `f`; if it prints a row of changing numbers as you move the joints by
hand, they're feedback servos (one column per feedback joint).

**How it works** (`OpenCatEsp32/src/espServo.h`, `readFeedback()` /
`readAllFeedbackFast()`): the servo reports its angle back **on the same PWM
signal wire**. The firmware, per joint: re-attaches the pin, writes a special
~3500 µs pulse (wider than the 500–2500 µs command range) to request a reply,
**detaches the pin and sets it to INPUT**, then measures the width of the pulse
the servo sends back and converts it to an angle. It takes 3 samples/joint and
discards the first; `delay(15)` ms per joint (or a shared `delay(3)` in the "fast"
all-joints path); 10 ms timeout per pulse.

**This is NOT a control-rate signal.** Reading is blocking, time-multiplexed, and
**momentarily interrupts the PWM command** on each pin while it reads. A full
9-joint read is on the order of tens of ms → realistically **~5–20 Hz**, versus
the 80 Hz sim control loop (or the real BiBoard's ~48–50 Hz). You cannot command
and read feedback on the same wire at the same rate.

**Serial interface** (over the same link `pi_pipeline` already uses):
`f` = print one feedback row · `fF` = "movement following" (drag a leg, others
mirror) · `fl` / `fr` = record / replay a hand-puppeted skill · `c16` = auto
joint calibration. The higher-level modes need **all** joints to be feedback
servos.

**Implications for our work:**
- → **The RL policy must not depend on fast measured joint angles.** Good news:
  in **residual mode** (the whole resid + survive line) `opencat_gym_env.py`
  already builds its joint-angle observation history from the **commanded**
  target (`ref + action·scale`, `step()` ~line 224), not from `getJointStates`.
  The Pi knows those without any feedback read → no sim-to-real gap here. This
  only becomes a problem if residual mode is turned off, or a term that reads
  *measured* angles is added.
- → The IMU (quaternion + angular velocity) is the only true real-time body
  signal — feedback servos don't change that.
- → Where feedback IS useful for the project: one-time **auto-calibration** on
  assembly, a **"puppet a skill" authoring flow** (backlog: "teach me a trick"),
  quasi-static **stalled/blocked-joint detection**, and sim-to-real calibration
  spot-checks — all things that tolerate a slow, blocking read.

## Bittle X body + battery

| Spec | Value |
|---|---|
| Joints | 9 servo DOF (2/leg + 1 neck); **no roll-axis joint** |
| Size / weight | 190 × 153 × 107 mm standing / 269–353 g |
| Battery | 7.4 V 1000 mAh 2S Li-ion, 2 A typ. / **5 A peak** draw |
| Runtime / charge | ~1 h walking / 1.5 h charge; **charger not included** (USB 5 V 1 A) |
| Top speed | ~2 body lengths/s (~0.38 m/s) |

- → The **5 A peak** servo-stall spike is exactly what the separate-Pi-power
  decision protects against (see [`pi-power.md`](pi-power.md)).
- → **~1 h runtime** caps how long a hardware eval/training session runs before a
  battery swap.
- → Our RL `TARGET_SPEED` of 0.10 m/s is ~1/4 of the servo envelope — a
  deliberate stability choice, not a hardware ceiling.

## Petoi AI Vision Camera Module (Seeed Grove Vision AI V2)

| Spec | Value |
|---|---|
| Processor | Himax WiseEye2 HX6538 — dual-core Arm Cortex-M55 + Ethos-U55 NPU (64–512 GOP/s) |
| Camera | OV5647 CSI (Raspberry Pi cam), 62° FOV recommended; other CSI cams may render green-only |
| Model input | **192 × 192** |
| Object detection | ~10–30 FPS (~76 ms YOLOv8n); ~0.35 W |
| On-device models | YOLOv8, YOLOv5, MobileNet V1/V2, EfficientNet-lite |
| Host link | I²C (addr `0x62`) or UART for results; **raw images over USB-serial only** |
| Outputs | `boxes` (x,y,w,h,score,target — centre + size in model px), `classes` (target+score), `points` (x,y + **relative** z, score, target), `perf` (pre/inference/post ms) |
| Extras | onboard PDM microphone, SD-card slot |
| Camera mode toggle (BiBoard) | serial `XC` on / `Xc` off (mobile-app codes `X67` / `X99`) |

- → **Detections OR the live frame — never both at once** (Seeed's own FAQ). A
  host consuming the detection stream cannot also pull raw frames. This affects
  `pi_pipeline/vision/`: the obstacle-avoidance reflex (needs detections) and
  Claude scene-narration (needs a frame) must **timeshare or mode-switch**, not
  run concurrently. Results and frames do travel different links (UART vs USB),
  which may make timesharing easier.
- → **192 × 192 model input** ⇒ short effective detection range. Thin objects
  (cables) are only seen when close / large in frame — relevant to the Phase 8
  "steps over cables it sees" goal and to how far ahead an RL policy could ever
  get obstacle info.
- → **~10–30 FPS** vs the 80 Hz control loop ⇒ vision features refresh only every
  ~3–8 control steps. A vision-conditioned policy must assume stale-between-frames
  obstacle data.
- → **Swapping models takes 1–2 min** — no runtime switching between, say, an
  "obstacle" model and a "person" model. Use one multi-class model.
- → `classes()` (classification, no box) is the light path for a camera-based
  **"floor vs. edge-ahead" cliff classifier** — the only option for cliff/edge
  sensing, since the single module slot is taken and there's no room for a
  dedicated distance sensor.
- → Petoi ships a real custom-model pipeline (actively maintained): a COCO-subset
  "DIY" picker, or Label Studio / Roboflow → YOLOv8 in Colab → quantised TFLite →
  Vela optimise → deploy via SenseCraft. "Small objects it sees" = a custom
  YOLOv8n on a chosen label set.

## Raspberry Pi Zero 2 W

| Spec | Value |
|---|---|
| SoC | RP3A0 SiP — quad-core Arm Cortex-A53 @ 1 GHz (64-bit) |
| RAM | **512 MB** LPDDR2 |
| Radios | 2.4 GHz Wi-Fi b/g/n, BT 4.2 + BLE |
| I/O | microSD, mini-HDMI, micro-USB OTG, CSI-2 camera, unpopulated 40-pin header |
| Lifecycle | in production until at least Jan 2030 |

- → **512 MB RAM is the hard ceiling** for anything on-Pi — local Whisper/VLM are
  borderline-to-infeasible (matches the pidog-embodiment benchmarks noted in
  Phase 8). Favours cloud STT + Claude-side scene reasoning.
- → The Pi's CSI connector is unused — the camera goes to the Grove Vision module,
  not the Pi.

## PiSugar S 1200 mAh

| Spec | Value |
|---|---|
| Output | 5 V / 2 A max |
| Battery | 1200 mAh single-cell (4.2 V max), USB-C charge |
| Mode | true pass-through (charge + discharge together), physical disconnect switch |
| Pi support | Pi Zero 2 (W/WH) officially listed |
| Comms | **none — hardware only** |

- → **No I²C, no battery-percentage readout in software.** `pi_pipeline` can only
  sense "external power present", not battery state or voltage. Battery telemetry
  would need a PiSugar 3.
- → PiSugar S's auto-boot-on-power and GPIO-button features use the I²C SCL pin —
  **conflict with enabling I²C on the Pi.** If I²C is ever needed on the Pi,
  disable those PiSugar features (it has a switch for the auto-boot one).
- → Confirms the Pi Zero 2 W side of the power plan; the BiBoard 5-pin Pi socket
  compatibility is still the open item.
