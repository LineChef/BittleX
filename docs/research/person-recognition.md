# Person recognition + enrollment ("G2, meet X")

How G2 comes to recognise household members, and the guided photo-capture
routine that builds the training data. Companion doc:
[`detection-layer.md`](detection-layer.md); behaviour backlog entry
[`../behavior-ideas.md`](../behavior-ideas.md) **B15**.

Status 2026-09-06: the enrollment **FSM is built** (`pi_pipeline/behavior/
enrollment.py`, 15 tests). The **driver** that wires it to hardware is not.
No recognition model exists yet (the practice model was a dud — weak dataset).

---

## Why recognition matters

It's not a nice-to-have — the personality / bonds / memory design *depends* on
G2 knowing who it's talking to: greet `dad` warmly, keep distance from a
`fearful`-tagged person, pull the right person's memory context, personalise
Claude's replies. Without it G2 is a generic assistant with no relationships.
`personality/bonds.py` is already built and waiting for real per-individual
detection labels.

---

## Which kind of recognition

| Approach | Output | Feasible on Grove Vision AI V2 |
|---|---|---|
| Person detection (deployed now) | box around any human | ✅ one model, frame rate |
| Face detection | box around any face | ✅ — but *less* useful than person detection for "someone's here" (a face only shows close + facing) |
| **Per-individual detection** (the near-term plan) | `dad`, box, 0.7 | ✅ one model, frame rate — **coarse** at 192–240 px, confuses similar faces, retrain to add anyone |
| True face recognition (detect → embedding → gallery match) | vector per face, match against a few enrolled photos, **no retrain to add people** | ⚠️ two models — module runs one at a time → face-detect on module + embed on the **Pi**, event-driven (module can't stream a frame *and* detections) |

**Near-term:** per-individual detection. One `interaction` model with classes
`person` + `dad` + `mom` + `dog` + …, trained via SenseCraft (multi-class
project) or the SSCMA/Colab path (fine-tune from a person-aware Swift-YOLO
checkpoint). Include a generic `person` class so unknown people still register
(feeds Bonds' "new person → curious" default).

**Upgrade path if per-individual proves too confusable:** face-detect on the
module → Pi crops the face box → Pi runs a small face-embedding model →
match against a per-person gallery of a few reference crops. Add a person by
adding crops, no retrain. Costs: the module can't give detections + a raw frame
in the same cycle, so this is event-driven (a face appears → one recognition
pass), plus Pi Zero 2 W compute for the embedding (slow; low rate only). Worth
prototyping once the body is up and per-individual detection has been tried.

### Training-path comparison (do once, on a good dataset)

Same daylight set, three ways, compare detection rate / confidence / confusion:
1. Fresh SenseCraft "Image Object Detection" multi-class.
2. SSCMA/Colab fine-tune from a person/COCO-pretrained Swift-YOLO checkpoint.
3. SenseCraft multi-class `person` + individuals, feeding `person` a large batch
   of generic people shots so the shared backbone stays person-aware.

Dataset bar (from the 2026-09-06 practice failure): **80–120+ images per
person**, genuinely varied — window / lamp / overhead light, 3–4 spots,
distance 1.5–6 ft, head turns, chin up/down, ~15 negatives. Camera **propped
up** (hand out of frame), **fixed orientation**, and ideally captured with the
camera **mounted on G2** so frames are at the deployment POV.

---

## Enrollment mode — "G2, meet X"

A **commanded** guided-capture routine (not autonomous — see Consent below).
The user says "G2, meet Alex"; G2 talks Alex through a set of poses, capturing
frames the whole time, across **3 separate sessions** for lighting/pose variety.

### Flow

1. **Greeting** — G2: *"Nice to meet you, Alex. I need 3 sets of photos to get
   to know you. This is session 2 of 3, one more after this. Stay in front of me
   and follow along."* (Session count comes from how many completed sessions the
   person already has.)
2. **Scripted pose steps**, each = a spoken prompt + a capture window:
   - session 1 — basics: look at me / face close / back up / turn head / step out
   - session 2 — angles + light: face me (different light) / look left-right /
     chin up-down / step left / step right / step out
   - session 3 — movement: look at me / walk toward me / walk back / turn while
     moving / step out
   Scripts differ per session so 3 sessions aren't identical.
3. **Quality gating** — the driver scores each frame (`face_quality` 0–1 ≈
   brightness × face-box fraction); frames only count when good, and a sustained
   bad stretch earns one spoken hint (*"come a little closer"* / *"a bit more
   light on your face"*).
4. **Interruptions** — person walks off → G2 pauses (*"come back in front of
   me"*); gone too long → abort with a friendly close.
5. **Completion** — G2: *"Got it — that's set 2. Find me one more time later to
   finish."* or, on the last: *"That's all 3 sets, Alex. Ask my humans to train
   me on you now."*

### The FSM (`behavior/enrollment.py`) — BUILT

Pure logic + injectable clock, same pattern as `link/recovery.py` /
`behavior/idle_posture.py`. No I/O.

- `Enrollment(cfg=EnrollmentConfig(), clock=time.monotonic)`
- `start(name, prior_sessions=0) -> EnrollTick` — greets; goes straight to DONE
  if `prior_sessions >= sessions_required` (default 3).
- `update(now=None, *, person_present, face_quality, good_frames_this_step)
  -> EnrollTick` — advances GREETING → CAPTURING (per step) → DONE, with
  PAUSED / ABORTED branches.
- `cancel()` — abort.
- `EnrollTick`: `state`, `action` (`SPEAK` / `CAPTURE_ON` / `CAPTURE_OFF` /
  `ORIENT` / `COMPLETE` / `ABORT` / `NONE`), `speak` text, `step_kind`,
  `bearing`, `session_index`, `sessions_left`, `reason`.
- `build_script(session_index) -> list[EnrollStep]` — the per-session pose sets.
- `EnrollmentConfig`: `greeting_settle_s` 3.5, `between_step_s` 1.2,
  `max_step_s` 12, `person_lost_grace_s` 2.5, `abort_after_lost_s` 20,
  `bad_quality_nudge_s` 3, `sessions_required` 3.
- FS helpers (do I/O, separate from the FSM):
  `count_completed_sessions(root, name)`, `new_session_dir(root, name, k)`,
  `mark_session_done(session_dir)` → `training_data/faces/<slug>/session_<k>/`
  with a `.done` marker.
- `last_reason` exposed for `diag`.

### The driver — NOT BUILT (hardware-gated)

`pi_pipeline/behavior/enrollment_driver.py` (or fold into the voice loop's
command handling). Per tick it must:

| FSM needs | Driver supplies from |
|---|---|
| `person_present` | the `interaction`/`person` model via `SerialDetectionFeed` — any `person`/individual box this frame |
| `face_quality` | brightness of the face-box crop × (box area / frame) — needs the JPEG (`AT+INVOKE=-1,0,0` carries one per frame; reuse `scratchpad/face_preview.py`'s grab path) |
| `good_frames_this_step` | count of frames it accepted+saved since the last `CAPTURE_ON` |

And it must act on `EnrollTick`:

| action | driver does |
|---|---|
| `SPEAK` | `voice.tts.speak(tick.speak)` |
| `CAPTURE_ON` | `new_session_dir(...)` once per session; start saving accepted frames, tagged with `step_kind`; also save the detection box as a pre-label (YOLO txt) so upload is ~90 % labelled |
| `CAPTURE_OFF` | stop saving |
| `ORIENT` | turn body toward `tick.bearing` (only if a body/link is present) |
| `COMPLETE` | `mark_session_done(session_dir)`; tell the user; if `sessions_left == 0`, surface "ready to train" |
| `ABORT` | discard or keep partial (config); tell the user |

Trigger: voice command `"(hey )?g2,? meet (<name>)"` in the voice loop's local
command matcher (sibling of `voice/commands.py` "forget that" / "go to sleep").
Also a manual CLI entry for bench testing.

### Handoff to training

1. `python -m pi_pipeline ... sync-faces <dest>` (or scp) — pull
   `training_data/faces/<name>/` off the Pi.
2. Upload to SenseCraft; the pre-label boxes mean you mostly just assign the
   class name. Or import to Roboflow.
3. Train (multi-class — add the new person to the existing `interaction`
   dataset), deploy the updated model.
4. `.env`: add the name to `VISION_LABELS` (in class-id order) and
   `G2_BONDS` (`name:closeness:disposition[:kind]`).
5. `Bonds` now returns a real disposition for that label; before that, the
   person reads as generic `person` → `curious` default.

### Consent

Commanded only. A robot autonomously trailing a guest taking photos is
off-putting and has consent implications. An autonomous "unknown person nearby →
offer to enroll them" is a possible v2 once the quality filter is trusted, and
should *ask* ("I don't know you yet — can I take some photos?") before capturing.

### Testing plan (once the body is built)

1. **Mock driver** — feed the FSM synthetic `person_present` / `face_quality` /
   frame counts; assert the prompt sequence, pause/resume, abort, 3-session
   accounting (covered by `test_enrollment.py`; extend for the driver).
2. **Bench, camera only** — real `person_present` + `face_quality` from the
   feed, real frame saves, `SPEAK` to stdout/TTS, no body. Run a full 3-session
   enrollment on one person; inspect the saved sets for variety and quality.
3. **Full robot** — add `ORIENT`; test that G2 keeps the person framed as they
   move; tune `EnrollmentConfig` timings against real human pacing.
4. Then run the training-path comparison on the enrolled data.
