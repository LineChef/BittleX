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

Boxes are normalised `[0,1]`: `(x, y)` top-left, `(w, h)` size. `area` (`w*h`) is
the closeness proxy — a forward-facing camera sees nearer things bigger.
`center_x` gives bearing (`left` / `ahead` / `right`). This is a heuristic;
revisit once real detections show how the camera's FOV and mounting angle map to
distance.

## Still to do

- **Confirm the serial wire format** against real Grove Vision AI V2 / SenseCraft
  output and finish `SerialDetectionFeed` (`feed.py` has a provisional JSON-lines
  format).
- Train a custom detection model in SenseCraft (cables, small household objects,
  table edges) and note the deploy workflow.
- Tune `AvoiderConfig` thresholds against real detections + the robot's stopping
  distance.
- Cliff/edge avoidance — a "floor vs. edge ahead" classifier (single sensor slot
  is taken by this camera, so it must be camera-based). Higher stakes: a miss is
  a fall.
- Wire `Avoider` decisions to the actuator and `narrate` to the voice loop in the
  Phase 10 runtime.
- **After vision works, revisit the locomotion policy** with perception in the
  loop — the Phase 8 "Target capability" in the project plan.
