# Vision detector — measured behaviour (bench)

Numbers measured 2026-09-05 with the **Grove Vision AI V2** on USB to the Mac,
running SenseCraft's `swift_yolo_nano_person_192_int8_vela` (model id 60086,
single `person` class). These are the **mount-independent** characteristics —
they feed the sim noise model for a future perception-in-the-loop gait retrain
(Phase 8 / hardware-gated H-list). The **mount-dependent** parts (visibility
cone, range-vs-confidence falloff, pixel→ground geometry) still need the camera
fixed to G2 and measured against known distances.

## Firmware / module facts

| | |
|---|---|
| Name / FW | "Grove Vision AI V2", software `2025.01.02`, `at_api v0` |
| USB serial | CH343 bridge (VID `1a86` / PID `55d3`), `/dev/ttyACM0` / `/dev/cu.usbmodem*`, 921600 |
| Model slots | **one** — `AT+MODELS?` returns a single entry. Switching models = a full reflash (~1–2 min), *not* an instant `AT+MODEL=<id>` swap on this FW. |
| Sensor resolutions | 240×240 (default), 480×480, 640×480 — but the model runs at its own input size (192 here) and **reports boxes in the 240 frame** (`resolution:[240,240]`). `frame_px=240` is correct. |
| Box format | `[cx, cy, w, h, score, class_id]`, `(cx,cy)` = **centre**, pixels in the 240 frame, score 0–100. Only `type==1` INVOKE messages carry results. |
| Start / stop | module does not self-stream — send `AT+INVOKE=-1,0,1` (loop, results-only, no JPEG) to start, `AT+BREAK` to stop. `feed.py` does this. |
| Model-reselect + inference restart | ~0.5 s |

## Detector behaviour

Empty bench, 22 s / 340 frames → **0 false positives**.
Clear target (person, ~3–5 ft, centred, holding still), 25 s / 384 frames:

| Metric | Value | Note |
|---|---|---|
| Output rate | **~15 fps** | serial-limited |
| Inference time | **48 ms, deterministic** (min=max) | ~20 Hz raw; NPU is fixed-cost |
| Detection rate while present | **~83 %** → **~17 % dropout** | frames with 0 boxes despite the target being there |
| Confidence | mean **66**, range **50–87** (threshold 50) | sits close to threshold — winks in/out near range limits |
| Centre jitter (static target) | cx σ ≈ **5 px**, cy σ ≈ **3 px** | ~2 % of frame — bearing is fairly stable |
| Box-size jitter (static target) | w σ ≈ **18 px**, h σ ≈ **16 px** | **~7–8 % of frame — large.** area-as-distance will be noisy |

## Implications for the sim noise model

When the perception-in-the-loop retrain happens, the fake detector in the env
should reproduce, at minimum:

- **~15 Hz update, not the 80 Hz control rate.** Hold the perception signal
  stale between updates (≈5 control ticks per detection).
- **~50 ms latency** — shift the signal back ~1 control step.
- **~17 % random whole-detection dropout** even when the feature is in view.
- **Bearing noise small** (σ ≈ 2 % of frame), **distance/size noise large**
  (σ ≈ 8 % of frame → distance-from-area ≈ ±20–30 %).
- **Confidence near threshold** → detections flicker at range; model a
  probability-of-detection that falls off with distance (needs mounted-camera
  measurement to set the curve).
- **No false positives on a clean scene** — but this was a plain bench; a
  cluttered room may differ. Re-check once mounted.

## Still needs the camera mounted on G2

- Visibility cone: camera height, pitch, FOV → which ground distances are even
  in frame, and the blind wedge in front of the feet.
- Probability-of-detection vs. distance / vs. box position in frame.
- Pixel-box → (distance ahead, lateral bearing, height) mapping — the
  `terrain_feature.py` `fov_scale` / `s_near` / `s_far` / `h_tall` constants.
- Motion blur / vibration effect while walking.
- Low-light and backlit behaviour in the real room.

## Low-light: auto-exposure lift (bench, 2026-09-06)

Stock Himax tuning aims the OV5647 auto-exposure **dim** -- WPT/BPT target
regs `0x3A0F`/`0x3A10`/`0x3A1B`/`0x3A1E` default `~0x32`/`0x24`. In a dim
room that gave dark, low-signal frames and a poor detection hit-rate.
Adding **+0x20..0x30** to those four regs via `AT+SETREG` lifted mean
frame brightness ~108 -> ~166 and **markedly raised the person-detection
hit-rate** (user-confirmed on the live feed). Runtime-only -- lost on
power-cycle, so re-applied on every open.

Wired: `SerialDetectionFeed(sensor_opt=, ae_bump=)`, config
`VISION_SENSOR_OPT` (default 1 = 480 capture, cleaner downscale, boxes
come in that frame -- feed reads the per-message `resolution`) and
`VISION_AE_BUMP` (default 32).

**TUNE on the mounted camera** under real on-robot lighting: a fixed lift
over-exposes a bright scene, and it trades against motion blur (longer
exposure). Options if a fixed value isn't good enough: adaptive (read
frame brightness, adjust), or gain instead of exposure (brighter without
blur, noisier). Hardware-gated.

## Camera orientation vs. detection (2026-09-06)

The OV5647's native readout is fixed; **physically rotating the module
rotates the scene within the frame.** With the module in one orientation
the person came out sideways and the *library* Person-Detection model
(trained on upright people) hit only **~13%** of frames -> few pre-labels.
Rotating the module so the raw feed is **upright** took the hit-rate to
**100%** (score ~87). Lesson: mount the camera so its *raw* output is
upright, and use that as G2's mount orientation. A custom model trained on
either orientation works (train == infer), but upright lets you use
pretrained upright models and get clean pre-labels. Curate then needs
`--rotate 0`.
