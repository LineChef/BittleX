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

- Launch `scratchpad/face_preview.py`, open `http://localhost:8080`.
- It saves `<name>_NNNN.jpg` + `<name>_NNNN.json` (the detection boxes — the
  sidecar `curate` needs for pre-labels). Clean frames, no overlay burned in.
- Camera **fixed orientation** the whole session, desk height, angled up.
- Pose sequence, ~60–100 keepers, hit "Start"/"Stop" between changes:
  - distances: close (~1.5 ft) / mid (~3 ft) / far (~5–6 ft)
  - angles: straight on / both 3/4 profiles / chin up / chin down
  - lighting: 2–3 spots (near window / away / lamp on-off)
  - hair up **and** down per how the person normally wears it (bulk = normal)
- Then ~15 **negatives**: step fully out of frame / point at an empty wall.

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
