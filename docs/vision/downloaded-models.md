# Downloaded models (outside the repo)

Rule (user, 2026-10-07): nothing is downloaded from the internet without telling the user first and waiting for a yes. Models live in `~/g2_data/models/` on the Mac, never in the repo. Each is checked against the hash its host publishes.

| File | Source | Size (bytes) | SHA-256 | Checked against | Approved |
|---|---|---|---|---|---|
| `dinov2_small.onnx` | Hugging Face, `onnx-community/dinov2-small`, `onnx/model.onnx` (Meta's DINOv2 small, Apache 2.0) | 88,532,934 | `f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a` | the file listing on Hugging Face (LFS oid, size) | 2026-10-08 |
| `mobilenetv2-12.onnx` | GitHub, `onnx/models`, `validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx` (ONNX Model Zoo) | 13,964,571 | `c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5` | the Git LFS pointer in the repo (oid, size) | 2026-10-08 |
| `yolox_s.onnx` | Hugging Face (person detector for the picture curation) | | | downloaded 2026-10-07 BEFORE the rule existed, without asking; kept at the user's later approval | |

What the checks do and do not show: the hash proves the file is the one the host serves for that name, and the format (ONNX, a graph of math operations run by onnxruntime with no custom operator libraries) cannot run code the way a pickle file can. They do not prove that the publisher's account is clean, and nothing was scanned for malware or run in a sandbox.

Used by `tools/eval_embedder.py --embedder onnx:~/g2_data/models/<file>` (DINOv2: add `#cls` for the class token only; the default joins the class token and the mean of the patch tokens).


## DINOv2-small as the gallery's embedder (2026-11-06, no new download)

The user asked for the learned embedder to be set up. The file was already on the Mac and checked (table above), so nothing new was downloaded; `tools/g2_switch_embedder.sh push-model` copied it to the Pi's `~/.local/share/g2/models/dinov2_small.onnx` and checked the same SHA-256 there. On the 398 promoted pictures (20 objects), `tools/rebuild_gallery.py --dry`: same-object pairs 0.617 vs different-object pairs 0.345 (gap 0.272, the histogram's gap is 0.099); at thresholds chosen from that data (0.582 same-instance, 0.774 near-duplicate) 60% of same-object pairs are recognised against 4.3% of different-object pairs wrongly matched, where the histogram recognises 23% at 3.8% wrong. Leave-one-out 96% against 93%. On the Mac it takes 66 ms a picture and about 190 MB; the Pi has not been timed yet (it needs the voice service stopped).

The gallery file now records its embedder and its thresholds, and every part of the Pi uses the gallery's own: switching is `g2embedder bench`, `g2embedder switch`, and `g2embedder revert` undoes it. The rebuilt gallery is at `~/g2_data/gallery_rebuilt/gallery.json` (19 entries; one pair of look-alike names could not both be kept).
