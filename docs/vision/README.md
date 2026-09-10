# docs/vision/

Everything about G2's camera, the on-device detection model, and building /
capturing data for it.

| | |
|---|---|
| [`custom-model-recipe.md`](custom-model-recipe.md) | **Start here for a model.** The reproducible custom-detection-model recipe — why the frozen Jan-2025 camera firmware breaks modern export toolchains, the `ultralytics==8.2.8` + local-arm64-export path, `tools/gv2/`, the 12-step process. |
| [`capture-progress.md`](capture-progress.md) | Live tracker: per-class image counts, the diagnostic `vision_diag` logging pass, the shot list for improving the 3-class model. |
| [`capture-checklist.md`](capture-checklist.md) | The routine to run for every capture session. |
| [`detection-layer.md`](detection-layer.md) | Architecture: one model slot, three roles (safety / interaction / objects), a model-manager that swaps by mode. |
| [`person-recognition.md`](person-recognition.md) | B15 — individual recognition + the "G2, meet X" enrollment flow. |
| [`detector-bench.md`](detector-bench.md) | Measured on-device detector behaviour (rate, latency, dropout, noise) + confirmed firmware facts. |

The runtime code is `pi_pipeline/vision/` (feed / avoidance / cliff-guard /
scene). The SenseCraft single-class flow is [`../guides/train-vision-model.md`](../guides/train-vision-model.md).
