# Vision — Phase 8

The AI Vision Camera Module runs object detection **on-device** and sends
results to the Pi over serial (BiBoard's ESP32 can't stream frames — see the
project plan). This package turns that stream into detections and does two things
with them:

1. **Local obstacle-avoidance reflex** — fast, no network. `avoidance.py`.
2. **Scene description** — "what do you see" answered in G2's voice via Claude.
   `scene.py`. Decoupled: it takes an `ask(str) -> str` callable, never imports
   `voice`.

As with voice/memory, every hardware-specific piece is behind an interface with
a mock, so it's all testable now.

## Modules

| File | Role |
|---|---|
| `feed.py` | `Detection` + `DetectionFeed`: `MockDetectionFeed` (scripted frames, `approaching()` scenario builder) / `SerialDetectionFeed` (parses camera serial messages). |
| `avoidance.py` | `Avoider.decide(frame) -> AvoidanceAction` (`NONE`/`STOP`/`BACK_UP`/`TURN_LEFT`/`TURN_RIGHT`). Debounced; urgent hazards preempt the cooldown. `ACTION_SKILL` maps actions to robot skills. |
| `scene.py` | `summarize(frame)` (deterministic text) and `narrate(frame, ask)` (spoken-style, LLM-injected). |
| `__main__.py` | demo CLI. |

## Try it (no hardware)

```bash
python -m pi_pipeline.vision demo               # obstacle approaching dead ahead
python -m pi_pipeline.vision demo --bearing 0.2 # ...from the left
python -m pi_pipeline.vision serial /dev/ttyAMA1   # real feed (hardware)
```

The demo prints each frame's scene summary and the avoidance decision, showing
the escalation `none → turn → stop → back up` as the object closes in.

## Detection model

Internally, `Detection` boxes are top-left, normalised `[0,1]`. `area` (`w*h`) is
the closeness proxy — a forward-facing camera sees nearer things bigger;
`center_x` gives bearing (`left` / `ahead` / `right`). Heuristic; revisit once
real detections show how the camera's FOV and mounting angle map to distance.

## Camera serial format (Grove Vision AI V2 / SenseCraft SSCMA)

Confirmed from the [SSCMA AT protocol](https://github.com/Seeed-Studio/SSCMA-Micro/blob/dev/docs/protocol/at_protocol.md).
One JSON object per line, **921600 baud**:

```json
{"type":1,"name":"INVOKE","code":0,
 "data":{"count":8,"perf":[8,365,0],
         "boxes":[[x, y, w, h, score, target_id], ...]}}
```

- `boxes` values are **integers**: box **centre** `(x, y)` and size `(w, h)` in
  **model-input pixels** (192 or 240 for common pretrained models — set
  `VISION_FRAME_PX`), `score` 0–100, `target_id` a class index.
- **Labels are not in the message.** Set `VISION_LABELS` to the deployed model's
  class names in id order (empty → `obj<id>`).
- `perf` = `[preprocess_ms, inference_ms, postprocess_ms]`; other events ignored.

`SerialDetectionFeed` parses exactly this.

## Still to do

- Train a custom detection model in SenseCraft (cables, small household objects,
  table edges) and record the deploy workflow + its label list / input size.
- Verify centre-vs-corner and the pixel frame size against a live module (sources
  slightly disagree; the sscma struct says centre).
- Tune `AvoiderConfig` thresholds against real detections + the robot's stopping
  distance.
- Cliff/edge avoidance — a "floor vs. edge ahead" classifier (single sensor slot
  is taken by this camera, so it must be camera-based). Higher stakes: a miss is
  a fall.
- Wire `Avoider` decisions to the actuator and `narrate` to the voice loop in the
  Phase 10 runtime.
- **After vision works, revisit the locomotion policy** with perception in the
  loop — the Phase 8 "Target capability" in the project plan.
