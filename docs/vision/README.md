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
| [`exploration-object-learning-plan.md`](../planned/exploration-object-learning-plan.md) | **The plan (2026-10-07):** exploration survey pictures, naming objects by voice, processing the pictures, recognition, "what am I looking at?" and "I see the ...". |
| [`downloaded-models.md`](downloaded-models.md) | **Models downloaded from the internet (outside the repo):** source, size, SHA-256, what each was checked against, who approved it, and what those checks do and do not show |
| [`detector-bench.md`](detector-bench.md) | Measured on-device detector behaviour (rate, latency, dropout, noise) + confirmed firmware facts. |

The runtime code is `pi_pipeline/vision/` (feed / avoidance / cliff-guard /
scene). The SenseCraft single-class flow is [`../guides/train-vision-model.md`](../guides/train-vision-model.md).

## Reviewing the pictures G2 takes

`g2pics` opens a local review page of the pictures G2 saved while exploring: thumbnails with an X on each (a Trash with Undo; only "Empty trash" deletes for good), a Name button, quality and duplicate filtering, and Promote, which copies a labelled picture into the training set the Pi's gallery learns from. `g2pics pull` copies the pictures from the Pi first. The page is `tools/g2_review.py`; all helpers: [`../guides/shell-helpers.md`](../guides/shell-helpers.md), tool index: [`../../tools/README.md`](../../tools/README.md).
