# Exploration object learning: plan (2026-10-07)

How G2 builds a library of objects he has seen while exploring, learns their names from you by voice, and says what he recognizes. This is the build
plan for the Pi-side layer decided in B20 ([`../behavior-ideas.md`](../behavior-ideas.md), "Generic objects recognition"; the decision logic is
`pi_pipeline/vision/object_gallery.py`). The AI camera's own model stays as it is; everything here works on pictures, not on the camera's trained classes,
so it can learn things the camera model was never trained on.

## Your feedback, and where each item lives in this plan

| What you asked for | Where |
|---|---|
| Does taking a snapshot make an API call? If not, use snapshots | **No.** A snapshot is one USB request to the camera (`AT+INVOKE=1,0,0`); the API is called only when a picture is attached to a message to Claude. Phase 1 uses snapshots only; nothing in this plan calls the API. Tests use fakes (standing rule, 2026-10-07). |
| G2 walks a bit, stops, does the inspect pose, looks down and up | Phase 1: a survey stop at the end of each exploration leg |
| One picture looking down, one looking up, then keep exploring | Phase 1: `survey_plan` (bow, stand, one picture once the stance settles, walk on) |
| Name things by voice; you will try it in exploration testing | Phase 1 (saving a named picture) and Phase 5 (recognition from the saved names) |
| Explain how naming would work | Phase 5, and the user test script below |
| A routine to process the exploration pictures, like the capture sessions, so training data is good | Phase 2: `tools/curate_exploration.py` (reuses the capture tools' quality gates) |
| When G2 sees an object he has not seen and that has no name, he asks "what am I looking at?" | Phase 5: the ask |
| When he recognizes an object, he says what he sees, so we can tell it is working as he learns | Phase 5: the announce, plus a log of every recognition |
| Start recognizing objects outside the AI camera model's training | The whole plan: the gallery recognizes by similarity, not by trained class |
| A comprehensive plan that includes all of this feedback | This page |
| "Loop me in when you are in a good spot to talk about it" | Checkpoints below: the first is after Phase 1 is built and tested, before it goes on G2 |
| Pictures and your privacy | Pictures stay on the Pi; copying them to the Mac for processing needs your OK each time; people are skipped in the curated set (decision 3) |

## What exists, what is new

- **Exists:** the gallery's decision logic (new / same / duplicate / too low quality / capacity), the exploration state machine, the picture helper for the
  voice service, the capture-session tools (`tools/curate_captures.py`, `tools/auto_process_captures.py`, `tools/optimize_library.py`).
- **Built 2026-10-07 (Phase 1 code, tested with fakes, not yet on G2):** a one-picture call on the camera feed (`feed.snapshot()`), the survey stop and
  naming choreography (`behavior/survey.py`, driver, bindings), the "this is a <name>" parser.
- **Built since:** saving and labelling the pictures, the exploration wiring, and the processing tool (`tools/curate_exploration.py`, Phase 2).
- **Not built:** the embedding model, the localizer, recognition, the ask and announce.

## How identifying a specific object works (plain words)

1. **Every picture gets a fingerprint:** a small model turns a picture (or a crop of it) into a list of numbers; pictures of the same thing give similar lists.
2. **Naming:** you say "this is a mug" with the mug in view. G2 saves that picture under the name and its fingerprint in the library, locked so it is never forgotten.
3. **Recognizing:** a later picture whose fingerprint is close enough to a named one makes him say "I see the mug". A fingerprint that matches nothing becomes an unnamed entry, and he may ask
   "What am I looking at?" (the ask, limited by cooldowns).
4. **Boxes:** the first version needs none. It fingerprints the whole picture plus an overlapping grid of tiles (Phase 4, v0). Drawing a box around the object comes with the localizer (Phase 4, v1),
   only if the tiles prove too coarse. The on-camera detector's own boxes (faces and the like) are already saved in each picture's sidecar, and the curation tool can draw those on contact sheets.

## Status of the processing tool (checked 2026-10-07)

What exists on the Pi today: **duplicate removal** (a near-duplicate is never written, see Retention) and a JSON sidecar per picture. **Built 2026-10-07 (tested with synthetic pictures, not yet run on real ones):** the curation script
`tools/curate_exploration.py` (shell alias `g2picscurate`; `g2pics pull` is the pull helper): scores brightness, contrast, sharpness and clipped highlights; sets aside pictures with people (listed in the
manifest, never copied); rejects too dark / blown out / blurry / flat survey pictures; flags weak named pictures instead of rejecting them; removes near-duplicates (12 bits within a survey pose, 3 within a name) keeping the
**best-scoring** picture of each cluster (not the earliest, so the kept one has the best lighting and sharpness); writes `keep/`, `rejects/<reason>/`, a contact sheet per group (green = kept, orange = weak or rejected,
the camera's own boxes in red), `manifest.json` and `summary.txt` with hints per pose and per name. The older `tools/curate_captures.py` is for the capture-session photo library, not for these pictures.
Thresholds are the capture tools' defaults and will need tuning on the first real pictures (floor-level views are dim).

## Phases

### Phase 1: survey stops and voice-named pictures (code done, wiring in progress)
1. Feed: `SerialDetectionFeed.snapshot()` stops the detection loop, takes one picture on the same USB port, restarts detection (about one second dark).
2. Survey: at the end of an exploration leg, at most once every 15 s: stop, stand, `kbuttUp` (the nose-down inspect bow, looking down), picture, `ksit`
   (chest raised, looking up), picture, stand, walk on. Skill names and delays are in `SurveyConfig` (the sit pose is a guess at "look up": judged from the
   pictures).
3. Naming: wake word, then "this is a mug" / "remember this as my mug" / "call this the mug": G2 stops and takes the picture the same way as a survey stop (look down, look up, stand, settle, then one picture, saved under
   that name; user, 2026-10-07: one picture sequence for every picture), says "Okay, I will remember the mug", and walks on. Works inside an exploration session (roaming or stationary) **and in plain voice mode** (no session needed; the voice service runs the same sequence and saves the picture the same way, with no Claude call; user, 2026-10-07: naming must always be available).
4. Saving: `vision/exploration_pictures.py` writes each JPEG with a JSON sidecar (time, pose, what the on-camera detector saw, brightness) to
   `~/.local/share/g2/explore_pictures/survey/<date>/` and `.../named/<name>/`. No pruning of the survey pictures (they are the data set), a size warning
   in the log.
5. Wiring in `explore_session.py`: survey on by default (`G2_EXPLORE_SURVEY=0` turns it off), the listener gets the naming command.
6. Tests: the feed with a fake serial, the plans and parser, the driver emitting the right effects at the end of a leg and for a name request, the
   bindings, the saver. Full suite green.

**Checkpoint A (you are looped in):** Phase 1 built and tested, deployed to the Pi, the test script below ready. Nothing runs on G2 without your go.

### Phase 2: process the exploration pictures like a capture session (built 2026-10-07; run it after the first real session)
`tools/curate_exploration.py IN_DIR OUT_DIR`, run on the Mac after you OK copying the pictures:
1. Score every picture (brightness, contrast, sharpness, clipped highlights) with the capture tools' functions; reject dark, blown, blurry, low contrast.
2. Near-duplicate removal (average hash), keeping the earliest, as the capture tools do.
3. People: pictures where the on-camera detector saw a person or face are set aside, not curated (decision 3).
4. Named pictures are grouped by name (kept even if they only barely pass, flagged when they do not).
5. Outputs: a `keep/` set, rejects by reason, a contact sheet per session, `manifest.json` (scores, pose, detections, reject reason), and a summary of how
   many pictures per pose and per name, with hints (for example "look-up pictures are mostly ceiling").
6. A pull helper (`tools/g2_explore_pictures.sh pull|status`) and a shell alias, as for the capture sessions. Input is never modified.
Output location: `training_data/exploration/<session>/` (not tracked by git, like the vision photo library).

### Phase 3: choose the embedding model, offline

**Status (2026-10-07, user asked to start the build):** the plumbing is built and tested without any model file: `vision/embedder.py` (a `HistogramEmbedder` baseline that needs nothing downloaded, and an `OnnxEmbedder` for any exported image model), `vision/localizer.py` (v0 of Phase 4: the whole picture plus a 3 x 3 overlapping tile grid), `vision/recognizer.py` (learn a named picture, recognise by the best view, never rename a look-alike of a differently named entry), `ObjectGallery.match()` (ask without learning), and `tools/eval_embedder.py` (within-object against between-object similarity, leave-one-out retrieval, hit rate on held-out pictures, false recognitions in survey pictures). First numbers for the baseline on G2's real pictures (4 dishwasher pictures, 11 survey pictures): within-object similarity 0.68, hit rate 25% at threshold 0.80, 18% of survey pictures falsely recognised: weak, as expected. The learned models wait for the user's yes to download one (CLAUDE.md hard rule) and for more named objects (the gap needs two or more).

1. Collect the first data: two or three exploration sessions of about 30 minutes plus the objects you name.
2. Candidate small models (MobileNet-class, a small CLIP-style, a small DINO-class), run on the Mac over the curated pictures.
3. Measure: do pictures of the same named object across poses land close together, and different objects apart (retrieval accuracy, the gap between
   same and different similarity), on G2's low, dim, 240 px view.
4. Pick one, export it to ONNX, and time it on the Pi Zero 2 W (milliseconds per picture, memory, CPU heat); the budget is one embedding per crop, a few per
   survey stop. A model change later means starting the gallery over (noted in `object_gallery.py`).

**Model provenance and first comparison (2026-10-09, user's yes to the download):** MobileNetV2 (opset 12, exported from PyTorch 1.8) from the official ONNX Model Zoo, `https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx` (one redirect to GitHub's own file host `media.githubusercontent.com`), 13,964,571 bytes, SHA-256 `c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5` (the zoo publishes no checksum, so this is a record, not a comparison); license Apache-2.0 (the zoo's). Kept in `~/g2_data/models/mobilenetv2-12/`, outside the repo. Checked read-only: it parses, `onnx.checker` passes, only standard operators (Conv, Clip, Add, GlobalAveragePool, Gemm and the like), no custom-domain operators, and it loads in onnxruntime. The embedder uses a derived copy, `mobilenetv2-12-features.onnx`, whose output is the 1280 x 7 x 7 feature map before the pooling and classifier (the embedder then averages it to 1280 numbers).
On the 25 readable named pictures of 8 objects (6 cut-off survey pictures were left out), whole-picture vectors, threshold 0.80:

| | within-object | between-object | gap | leave-one-out retrieval | hit rate | survey pictures that "match" |
|---|---|---|---|---|---|---|
| histogram baseline | 0.781 | 0.588 | 0.193 | 82% | 82% | 68% |
| MobileNetV2 features | 0.788 | 0.687 | 0.101 | 77% | 73% | 46% |

Too little data to choose: most objects have 4-5 pictures, the survey pictures contain the named kitchen fixtures themselves (so some "false" matches are real), and 0.80 is not the right threshold for both scales. Rerun `tools/eval_embedder.py` once more objects have 5 or more labelled pictures. Time on the Pi Zero 2 W is still to measure when the Pi is online.

**Second model, DINOv2-small (2026-10-09, the user's yes):** a self-supervised image model trained to match the same thing across views, which is the property instance recognition needs (MobileNetV2 is a 1,000-category classifier: it groups kinds, not individuals). ONNX conversion by the `onnx-community` organization (a third-party export; Meta publishes only PyTorch weights) of `facebook/dinov2-small` (license Apache-2.0), pinned to commit `8b1f705a3a7f6f062f6bdd21986c1583d3ef105d`, file `onnx/model.onnx`, 88,532,934 bytes, SHA-256 `f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a` (matches the publisher's own checksum from the Hub API). Kept in `~/g2_data/models/dinov2-small/`, outside the repo. Checked read-only: parses, `onnx.checker` passes, only standard operators (MatMul, Softmax, Erf, LayerNorm pieces and the like), no custom-domain operators, loads in onnxruntime; one 224 px picture takes 0.06 s on the Mac. Output (1, 257, 384): class token plus 256 patch tokens, pooled by the embedder as class + mean (768 numbers). The 24 MB int8 file (`model_int8.onnx`, SHA-256 `dfce54a8...`) is the Pi candidate, not fetched.

| | within-object | between-object | gap | leave-one-out retrieval | hit rate at 0.80 | survey pictures that "match" at 0.80 |
|---|---|---|---|---|---|---|
| histogram baseline | 0.781 | 0.588 | 0.193 | 82% | 82% | 68% |
| MobileNetV2 | 0.788 | 0.687 | 0.101 | 77% | 73% | 46% |
| **DINOv2-small** | 0.756 | 0.534 | **0.222** | **91%** | 45% | 19% |

DINOv2 separates best (largest gap, best retrieval, fewest false matches) but its similarities sit lower, so the 0.80 threshold (set for the histogram scale) is too high for it: the hit rate at 0.80 is low only because of that. Next: tune the same-instance and duplicate thresholds for it on the labelled pictures (about 0.65-0.70 to start), time the int8 file on the Pi, then switch `G2_EMBEDDER` to it. Still only 25 named pictures of 8 objects; recheck after the first 5 labelled pictures per object.

### Phase 4: the localizer
1. v0: no localizer. Embed the whole picture and an overlapping tile grid (for example 3 by 3); the gallery's duplicate handling collapses repeats.
2. v1, only if v0 is too coarse: a foreground cut-out from the floor-level view (colour and edge difference against the floor, or motion while he is
   stationary), judged on the collected pictures.
3. Judged by: does the crop contain the named object in most named pictures.

### Phase 5: recognition, the ask and the announce (no API, no cloud)
1. Enable the gallery (`features.object_gallery`) inside the exploration session: every survey picture and named picture is embedded, scored for quality, and
   passed to the gallery.
2. Named picture: the gallery entry gets the name (and is locked against eviction).
3. **The ask:** a survey picture that matches nothing, whose crop is good enough, becomes an unnamed entry. G2 asks out loud "What am I looking at?" at
   most once per entry, with a cooldown (decision 4) and a per-session limit. Your answer ("this is a mug") names that entry; if you do not answer within a
   window, it stays unnamed and he does not ask again about it.
4. **The announce:** a survey picture that matches a named entry above the match threshold makes him say "I see the mug" (a cooldown per name, so he does
   not repeat). Every recognition, miss and ask is also written to the diagnostics log (name, similarity, picture file), so a session can be reviewed
   afterwards with the pictures next to it.
5. Thresholds start at the gallery's defaults (same instance 0.80, near duplicate 0.93) and are tuned on the collected data.

**Checkpoint B (you are looped in):** after Phase 3's model choice and before Phase 5 goes on G2: the thresholds, what he says, how often.

### Phase 6: evaluate with real sessions
Test protocol (each session about 30 minutes, you present): place five to eight ordinary objects at floor level; name three by voice; let him explore;
afterwards compare his announces and asks with what was in view (you note misses). Measures: recognized when present, wrongly recognized, asked about
things already named, ask rate. Iterate thresholds and the localizer; a result is only trusted after two sessions on different days or lighting.

### Phase 7: hardening and docs
Storage cap and tidy for the picture folders, battery and heat while the camera and embedding run, an audit confirming zero API calls from this path
(the API call log shows it), STATUS / plan / behavior-ideas updated, tests for each module.

## Your test script for the first session (after Checkpoint A, with your go)
1. Floor, clear space of about 2 m, no desk edge (there is no edge detector). `bash tools/g2_explore.sh start`, then `arm` (or say "go ahead and look around").
2. Watch for: he walks a leg, stops, stands, bows (looks down), a short pause (picture), sits up (looks up), a pause (picture), stands, walks on.
3. Put a mug on the floor in front of him and say the wake word, then "this is a mug". Expect: he stops, bows, says "Okay, I will remember the mug", walks on.
4. After about ten minutes: `bash tools/g2_explore.sh stop`, tell me, and I look at the pictures myself first.

## Retention and garbage collection (decided 2026-10-07)

Rule from you: **no picture is deleted unless it is a duplicate, and he does not forget what he has been taught.**

- **Pictures:** kept forever (`G2_PICTURE_KEEP_DAYS` default is now 0, and the exploration pictures never use an age rule). The only deletion is a near-duplicate: a
  picture whose 256-bit average hash is within 12 bits of one already saved for the same pose (3 bits for a named object, so its different views are kept)
  is not written at all, the earliest of a cluster is kept. Disk: about 15 KB each, a few MB per exploring hour; the log warns at 2 GB.
- **What he knows is the fingerprint index, not the pictures.** Entries you named, and entries locked as "enough data", are never evicted and do not count
  against the cap. Only unnamed, unlocked candidates (things he noticed but nobody named) are capped, at 300; over the cap the oldest unnamed one is
  forgotten, never a named one. Safety ceiling on all entries: 5,000 (new entries stop, nothing is removed). Samples per entry before it locks: 8.
- **Forgetting an unnamed candidate never deletes its pictures**, so it can be re-learned: the library can always be rebuilt from the pictures (also what makes a
  model change cheap).
- **To add when recognition is wired (Phase 5):** a daily snapshot of the gallery index (last 14 kept) so a corrupted file cannot erase what he learned; copying
  the index and named pictures to the Mac with `g2pics pull`; merging two unnamed candidates that converge (similarity above 0.85) instead of keeping both;
  matching in numpy (the pure-Python comparison is fine for hundreds of entries, too slow for thousands).

## Decisions to settle together (proposals in brackets)
1. How the look-up pose is done [`ksit`; replace after seeing the pictures].
2. How often he surveys [end of a leg, at most every 15 s].
3. People [skip frames with a person in the curated set; keep raw pictures only on the Pi and your Mac].
4. The ask [once per unnamed entry, 60 s apart, at most 5 per session, quiet voice, not while someone is talking to him].
5. The announce [once per name per 2 minutes].
6. What counts as "outside the camera model's classes": everything the gallery sees, including the people and pets the camera already knows, which the
   gallery will ignore [objects only].
7. Naming phrases [the four above plus "that is a ..."].

## Risks
- The look-up pose may only show ceiling: the first pictures decide.
- Embeddings of dim, low-resolution floor-level pictures may not separate objects: Phase 3 measures this before anything is built on it.
- Each picture pauses the detection feed for about a second: only at stops.
- Pi CPU and battery: measured in Phase 3 and 7.
- Personal data in pictures of the home: stays local; nothing is sent anywhere without asking.

## Status after the first on-G2 sessions (2026-10-07)

Phase 1 ran on G2 in the kitchen: survey stops (bow, look up, stand, settle, picture) work; after the camera fix (240 x 240, complete pictures) 15 survey pictures were curated by `tools/curate_exploration.py` (all kept: floor-level kitchen views, mean brightness 125, no duplicates, none cut off), the sheet is in `training_data/exploration/20261007_kitchen1/contact/`.
**No named pictures yet** (0 objects): naming now works in plain voice mode and inside a session, with feedback. For Phase 3 (the embedding model comparison) we need several named objects with 5 or more pictures each, plus a few more survey sessions; the 15 survey pictures are enough to exercise the curation pipeline end to end and to start tuning its thresholds, not to choose a model.
Camera lessons: the module's picture buffer cuts 480 x 480 pictures short (use 240 x 240 for pictures), and its detector reads bare floor as a cat or dog (filtered; see `vision/detection_filter.py`).

## Why the library matters (user, 2026-10-07)

Recognizing objects and scenes is meant to be the first step toward G2 having a **sense of where he is**: the pictures he takes while exploring, and the names he is taught, are the raw material for place memory (behavior idea B11, [`../behavior-ideas.md`](../behavior-ideas.md)). That is why clean pictures of the place are kept even when nothing in them is named,
and why the curation tool does not discard pictures just because they were taken near one that had a person in it. People are kept out of the object library when the models find them (the on-camera detector and, until the on-camera model is trained, an outside model) or when flagged by hand: legs and people seen from behind, which no model finds yet, are caught by hand (the user wants them excluded).
