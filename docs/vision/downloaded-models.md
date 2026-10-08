# Downloaded models (outside the repo)

Rule (user, 2026-10-07): nothing is downloaded from the internet without telling the user first and waiting for a yes. Models live in `~/g2_data/models/` on the Mac, never in the repo. Each is checked against the hash its host publishes.

| File | Source | Size (bytes) | SHA-256 | Checked against | Approved |
|---|---|---|---|---|---|
| `dinov2_small.onnx` | Hugging Face, `onnx-community/dinov2-small`, `onnx/model.onnx` (Meta's DINOv2 small, Apache 2.0) | 88,532,934 | `f22797eabf810a75e41de68d378541ebea372122b25c4ce3ef25ff618250c20a` | the file listing on Hugging Face (LFS oid, size) | 2026-10-08 |
| `mobilenetv2-12.onnx` | GitHub, `onnx/models`, `validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx` (ONNX Model Zoo) | 13,964,571 | `c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5` | the Git LFS pointer in the repo (oid, size) | 2026-10-08 |
| `yolox_s.onnx` | Hugging Face (person detector for the picture curation) | | | downloaded 2026-10-07 BEFORE the rule existed, without asking; kept at the user's later approval | |

What the checks do and do not show: the hash proves the file is the one the host serves for that name, and the format (ONNX, a graph of math operations run by onnxruntime with no custom operator libraries) cannot run code the way a pickle file can. They do not prove that the publisher's account is clean, and nothing was scanned for malware or run in a sandbox.

Used by `tools/eval_embedder.py --embedder onnx:~/g2_data/models/<file>` (DINOv2: add `#cls` for the class token only; the default joins the class token and the mean of the patch tokens).
