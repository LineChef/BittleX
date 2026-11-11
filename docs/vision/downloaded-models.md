# Downloaded models (outside the repo)

Rule: nothing is downloaded from the internet without explicit approval first. Models live in `~/g2_data/models/` on the Mac, never in the repo. Each is checked against the hash its host publishes.

- `dinov2_small.onnx`: Source: Hugging Face, `onnx-community/dinov2-small`, `onnx/model.onnx` (Meta's DINOv2 small, Apache 2.0); Size (bytes): 88,532,934; SHA-256: `f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a`; Checked against: the file listing on Hugging Face (LFS oid, size); Approved
- `mobilenetv2-12.onnx`: Source: GitHub, `onnx/models`, `validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx` (ONNX Model Zoo); Size (bytes): 13,964,571; SHA-256: `c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5`; Checked against: the Git LFS pointer in the repo (oid, size); Approved
- `yolox_s.onnx`: Source: Hugging Face (person detector for the picture curation); Checked against: downloaded before the approval rule existed; kept after later approval

What the checks do and do not show: the hash proves the file is the one the host serves for that name, and the format (ONNX, a graph of math operations run by onnxruntime with no custom operator libraries) cannot run code the way a pickle file can. They do not prove that the publisher's account is clean, and nothing was scanned for malware or run in a sandbox.

Used by `tools/eval_embedder.py --embedder onnx:~/g2_data/models/<file>` (DINOv2: add `#cls` for the class token only; the default joins the class token and the mean of the patch tokens).


DINOv2-small as the gallery's embedder (no new download)
--------------------------------------------------------

The user asked for the learned embedder to be set up. The file was already on the Mac and checked (table above), so nothing new was downloaded; `tools/g2_switch_embedder.sh push-model` copied it to the Pi's `~/.local/share/g2/models/dinov2_small.onnx` and checked the same SHA-256 there.

On the 398 promoted pictures (20 objects), `tools/rebuild_gallery.py --dry`: same-object pairs 0.617 vs different-object pairs 0.345 (gap 0.272, the histogram's gap is 0.099); at thresholds chosen from that data (0.582 same-instance, 0.774 near-duplicate) 60% of same-object pairs are recognised against 4.3% of different-object pairs wrongly matched, where the histogram recognises 23% at 3.8% wrong.

Leave-one-out 96% against 93%. On the Mac it takes 66 ms a picture and about 190 MB; the Pi has not been timed yet (it needs the voice service stopped).

The gallery file now records its embedder and its thresholds, and every part of the Pi uses the gallery's own: switching is `g2embedder bench`, `g2embedder switch`, and `g2embedder revert` undoes it. The rebuilt gallery is at `~/g2_data/gallery_rebuilt/gallery.json` (19 entries; one pair of look-alike names could not both be kept).

Derived file (not a download): `~/g2_data/models_derived/dinov2_small_int8.onnx` (23 MB) is `dinov2_small.onnx` with its weights stored as 8-bit integers (`onnxruntime.quantization.quantize_dynamic`, QUInt8), made on the Mac from the verified file above. On the 398 labelled pictures it separates as well as the full model (same-object 0.614, different 0.344, gap 0.271; 61% of same-object pairs recognised at 4.2% wrong matches against 60% at 4.3%) and runs in 38 ms a picture on the Mac (66 ms before) with a lower memory peak (143 MB against 190 MB). Use it on the Pi: `G2_MODELS_DIR` points `tools/rebuild_gallery.py` at the folder, and the gallery records the file name.
