# Parts list and hardware decisions

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> the finalized parts list ($567 as of this writing), resolved and open hardware questions, and the power-awareness plan. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## Parts list (finalized — $567)

| Item | Price |
|---|---|
| Petoi Bittle X V2 (alloy servos) | $380 |
| Raspberry Pi Zero 2 WH kit (pre-soldered headers, heatsink, mini-HDMI adapter, OTG cable) | $115 |
| SanDisk 32 GB Ultra microSDHC (A1, Class 10, UHS-I) | $22 |
| 5 V / 2.5 A micro-USB power supply | $10 |
| Petoi AI Vision Camera Module (Grove Vision AI V2, Arm Cortex-M55 + Ethos-U55) | $40 |
| PiSugar S 1200 mAh (independent Pi power — fits Pi Zero W/WH/2W; **not** the "S Plus") | — |
| Calibration stand (G2 sits with legs off the ground) — servo/gait bring-up without ever risking a fall; see `docs/guides/gait-deployment.md` step 6 | — |
| Dupont jumper wires, female-to-female, 40pc/10cm (bociloy, [B0D9NCD1Z3](https://www.amazon.com/dp/B0D9NCD1Z3)) — in hand 2026-09-18; used for BiBoard↔Pi TX2/RX2/GND (Step 3, `blueprints/biboard-pi-connector.md`); still need 20&ndash;30cm longer ones once the final mount position needs the longer run | — |
| [NULLLAB NS4168 I2S Audio Amplifier & 3W Speaker Kit](https://www.amazon.com/NULLLAB-NS4168-Audio-Amplifier-Speaker/dp/B0GV33LRR5) — ordered 2026-09-29, Pi-side TTS output, wires to the GPIO header (no USB, that port's reserved for the camera) | — |
| [HiLetgo SPH0645 I2S MEMS Microphone Breakout](https://www.amazon.com/HiLetgo-Microphone-Breakout-SPH0645LM4H-Raspberry/dp/B082KRJW62) — ordered 2026-09-29, Pi-side mic input, same GPIO header (shared I2S clock lines with the amp above) | — |

### Resolved

- **Pi power: independent, via PiSugar S 1200 mAh.** Drawing the Pi from Bittle's
  shared battery causes "reduced motion capability" (Petoi's own docs) and risks
  servo-spike brownouts. The PiSugar pogo-pins to the Pi's underside pads, leaving
  the GPIO header free, and provides UPS safe-shutdown. To avoid two 5 V sources,
  wire BiBoard → Pi **data-only (RX/TX/GND)**, no 5 V. Full reasoning:
  [`docs/hardware/pi-power.md`](pi-power.md).
- **Enclosure:** Petoi ships an official back-cover STL with a Pi cutout
  ([`Bittle_Cover_with_hole_for_Pi.stl`](https://github.com/PetoiCamp/NonCodeFiles/blob/master/stl/Bittle%20%26%20BittleX/BittleCover/Bittle_Cover_with_hole_for_Pi.stl)),
  so the cover can close over the mounted Pi. **2026-09-16: likely too shallow
  for Pi+PiSugar.** Measured its real bbox — 71.2 × **18.6** × 73.9 mm, and
  18.6 mm is the full outer depth (shell walls included), same clearance
  bottleneck as the standoff clips below, just from the enclosure side. A
  custom-modified version is now planned alongside the clips — see "Build:
  modified standoff clips + cover" below and `blueprints/biboard-pi-connector.md`
  for the full plan.
- **BiBoard V1 MCU:** standard **ESP32-U4WDH** (Xtensa dual-core LX6, via an
  ESP32-MINI-1 module), not an S3/C3. This is why Phase 8 sends structured
  detection results over serial rather than streaming raw frames. Flash is
  **4 MB**, SRAM **520 KB** (Petoi pages citing "16 MB / WROOM-32D" describe
  BiBoard V0). Board also carries a **6-axis MPU6050 IMU (no magnetometer)**, an
  onboard offline voice-recognition module, and a speaker.
- **Full vendor-doc spec sheet** for every part — with the "why it matters" for
  each — is in [`docs/hardware/specs.md`](specs.md).
  Key downstream effects: no magnetometer ⇒ favour **yaw-rate** over absolute
  heading in the RL reward (Phase 3); the vision module can stream **detections
  or a raw frame but not both**, and runs at 192×192 / ~10–30 FPS (Phase 8);
  the PiSugar S has **no battery-percentage readout** (hardware-only).

### Open (check when hardware arrives)

- ~~Confirm BiBoard V2 can be wired data-only~~ — **resolved 2026-09-14**: it's a
  discrete 5-pin header (TX2/RX2/GND/+5V/+5V), confirmed from Petoi's own
  official board diagram. Data-only wiring is straightforward. Full pinout +
  annotated photos: [`blueprints/biboard-pi-connector.md`](../../blueprints/biboard-pi-connector.md).
- BiBoard V1's spec lists Pi compatibility as "Pi 3A+, 4, 5" — the Pi Zero 2 WH
  isn't listed (the PiSugar S side *does* officially list Pi Zero 2 W/WH). Verify
  the 5-pin socket and serial wiring are compatible.
  **Researched, 2026-09-16 — leaning toward "probably fine," still not fully
  confirmed.** Checked Petoi's official serial docs directly
  ([overview](https://docs.petoi.com/apis/raspberry-pi-serial-port-as-an-interfac),
  [BiBoard V1 page](https://docs.petoi.com/apis/raspberry-pi-serial-port-as-an-interfac/for-biboard-v1))
  — neither mentions the Zero at all, positive or negative; only 3/4/5 are
  documented. But there's a real technical reason to expect it works: Petoi's
  docs say Pi 3 and Pi 4 both use `/dev/ttyS0` for this connection, which is
  a direct consequence of those SoCs reserving the PL011 UART for Bluetooth
  and falling back to the mini-UART. The Pi Zero 2 W uses a Pi-3-generation
  SoC with the **identical** PL011-to-Bluetooth arrangement, so it also
  defaults to `/dev/ttyS0` — same underlying serial architecture as the one
  family Petoi *does* confirm works, not an unconsidered edge case. Also
  found: Petoi's own Pi-mounting bracket (`Pi_StandOffRegular.stl`, already
  in use — see `blueprints/biboard-pi-connector.md`) is Zero-specific, which
  at minimum confirms Petoi designed real hardware for this board, even if
  that speaks to mechanical fit more than to serial compatibility. Net: good
  reason to expect it works, still worth the ~30-second confirmation once
  wired up rather than treating it as settled.
- Confirm the back cover fits once the Pi is mounted.
- BiBoard V1's onboard voice-recognition module + speaker: decide whether the
  wake trigger / offline fallback commands use it instead of the Pi (Phase 7).
  **2026-09-28**: confirmed present and controllable over serial (`X<letter>`
  commands, `docs/hardware/petoi-firmware-reference.md`) — found stuck
  defaulting to Chinese with voice unresponsive (no identified trigger,
  matches a known Petoi community incident), fixed via `XAc`/`XAb`/`XAa`.
  Can apparently get stuck again; the reset sequence is documented if so.

### Power awareness — G2 warns when it thinks it's running low

The PiSugar **S** gives no battery %, voltage, or low-battery signal (only
"external power present"), so G2 can't *measure* its charge — it has to
*estimate* from elapsed run time.

- **Plan:** track uptime since the last time it was on the charger; when it
  passes a learned threshold, G2 proactively says something in character ("I'm
  getting tired, might need to rest on the charger soon") via the voice
  pipeline, and repeats/escalates as it gets closer to the empirical limit. On
  the charger ("external power present" flips true) it resets and can say it's
  charging.
- **Needs first:** real battery-life data — run G2 doing representative work
  (idle, walking, talking, vision on) on a full charge until the Pi browns out,
  a few times, to get mean runtime and its spread. Do this early in hardware
  bring-up.
- **Built 2026-09-05:** `pi_pipeline/power/` (CPU governor / Wi-Fi power-save
  toggle / disable-unused peripherals) and `behavior/idle_posture.py` (idle-REST
  staged descent — sit, then lie down, with life signs). Battery-*aware*
  behaviour (rest sooner on low charge) is blocked on the estimate above.
  **Sleep-mode FSM built 2026-09-10** (`behavior/sleep_mode.py`). On-demand
  vision (the two-stream safety/rich split) is still a design task (B18). Full
  analysis: [`hardware/pi-power.md`](pi-power.md).
- **Later upgrade for a real signal (not just a timer):** an ADC on a BiBoard
  Grove analog pin (G3/G4) reading the pack voltage, so the warning is based on
  actual cell state. Optional; the timer is enough to start.

---
