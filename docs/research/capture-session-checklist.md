# Capture session checklist

The routine to follow **every time** we capture face/object images for training.
Companion: [`person-recognition.md`](person-recognition.md) (why),
`tools/curate_captures.py` (the filter), `scratchpad/face_preview.py` (live
preview + capture).

## 0 · Ask for the tag name

**Before anything else, ask the user what name to tag this batch with.**
That name is used everywhere: the capture folder, the curated folder, the YOLO
class, and later `VISION_LABELS` + `G2_BONDS`. Lower-case, short, no spaces
(`sam`, `mom`, `rex`). Also note **which session number** this is for that
person (`count_completed_sessions` from `behavior/enrollment.py`, or count
`session_*/` dirs).

## 1 · Check the rig

- Camera enumerated: `ls /dev/cu.usbmodem*`. Port free (close SenseCraft/Chrome
  tabs — the in-app "disconnect" does NOT release WebSerial).
- Which model is loaded: `AT+INFO?`. **Face Detection preferred** (tight face
  boxes → clean pre-labels + pos/neg split). Person Detection works but boxes
  are head+torso — tighten at upload. Redeploy from the SenseCraft library if
  switching.
- Lighting: get the room as bright as reasonably possible (all lamps, brightest
  daylight). Goal is *usable dim*, not near-black — the 2026-09-06 practice run
  failed on near-black frames. Capture under the lighting that's actually on
  when G2 is used, not the empty-room worst case.

## 2 · Prep the folder

`~/Desktop/g2_face_capture/<name>/session_<k>/` (or the Desktop root for a
quick one-off). Clear any stale `*.jpg`/`*.json` first.

## 3 · Capture (live preview)

- `g2cam <name> <session>` (or `python tools/camera_preview.py`), open
  `http://localhost:8080`. Saves `<name>_NNNN.jpg` + `<name>_NNNN.json` (the
  detection boxes `curate` uses for pre-labels). Clean frames, no overlay.
- Camera **fixed orientation** the whole session, desk height, angled up. Make
  sure the **raw** feed is upright (rotate the module until it is) — that's the
  mount orientation, and it takes the detection hit-rate to ~100%.
- Watch the **hit-rate** on the page — if it's not near 100%, the framing/
  orientation/light is off; fix it before capturing a lot.

### Standard pose set — run this every session

Same poses every time; the *variation* comes from a different room / lighting /
clothes / hair per session, not different poses. Hit **Start**, hold, **Stop**,
reposition, repeat. ~4 frames/sec.

| # | Pose | Hold | Notes |
|---|---|---|---|
| 1 | **Close** (~1.5 ft), straight on, neutral | ~8 s | small natural head movement |
| 2 | Close, talking + a smile | ~6 s | |
| 3 | **Mid** (~3 ft), straight on, neutral | ~8 s | |
| 4 | Mid — slow head turn: full left → full right → back | ~10 s | both 3/4 profiles |
| 5 | Mid — chin up (hold), then chin down (hold) | ~8 s | |
| 6 | Mid — look away: left, right, up (not at the lens) | ~6 s | |
| 7 | Mid — hand near face / push hair back | ~6 s | a little natural occlusion |
| 8 | **Far** (~5–6 ft), straight on | ~6 s | |
| 9 | **Second spot / different light** — repeat 1 + 3 (close + mid, straight on) | ~10 s | move near a window, or change which lamps are on |
| N | **Negatives** — step fully out of frame / point at an empty wall | ~12 s | ~50 empty frames |

≈ 250 raw frames → `curate` keeps ~80–120 usable. Aim for **~100 usable
positives per person across the 3 sessions**.

**Per-session variation:** session 1 can be one look (e.g. hair up); sessions
2–3 the person's normal look. Each session in a different room / lighting if you
can.

## 4 · Curate

```
python tools/curate_captures.py <session_dir> <session_dir>/curated \
    --positives 80 --negatives 15 --class-id 0
```

- Check `_summary.txt`: reject reasons, brightness/face-size range, balance
  hints. If good frames are tossed as "blurry", lower `--min-sharpness`.
- Check `_contact_sheet.png`: faces **upright**? if not, re-run with a different
  `--rotate` (0/90/180/270). Poses/lighting varied, not clumped?
- **Report the count:** curate prints *usable positives + negatives this session* and the *running total toward ~100* across the person's curated sessions -- always call that out so we know where we stand.
- Re-run with tweaked flags as needed — it's non-destructive (raw frames kept).

## 5 · Iterate / accumulate

- 3 sessions per person, different rooms/lighting/clothes. Session 1 can be one
  look (e.g. hair up), 2–3 the normal look.
- After each session, note it done. When all 3 curated folders exist, combine
  them for the upload.

## 6 · Handoff to training

Combine all `session_*/curated/` → upload to SenseCraft (multi-class: add this
person to the existing interaction dataset) → the YOLO `.txt` pre-labels mean
you mostly assign the class name → train → deploy → add to `VISION_LABELS` +
`G2_BONDS`. Full detail in `person-recognition.md`.

## Notes

- **Pre-label region:** `--label-region face` tightens the YOLO pre-label box to the face (from the Person box) -- the *image stays full-frame*. Do NOT crop the training images: an object detector must see faces *within* a scene to learn to localise them. `--face-crops` writes face crops to `crops/` only for a possible future classifier/embedder.
- **Resolution ceiling:** frames pulled over serial (`AT+INVOKE`) are the model-input frame, ~240 px max -- no raw high-res JPEG this way. Set sensor capture to 480 (`G2_CAM_RES=1` for `face_preview.py`) for a cleaner 240 downscale. Graininess past that is low light, not resolution; the detector runs at 192 px regardless.
