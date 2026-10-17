# tools/

Scripts that sit around the robot and the training code: documentation checks, Mac-to-Pi operations, the real-data pipeline, vision dataset work, and training support. The code that runs on the robot is in [`../pi_pipeline/`](../pi_pipeline/README.md), and the sim training in [`../rl_training/`](../rl_training/opencat-gym).

Paths here are stable: the `g2*` shell helpers ([`g2_aliases.sh`](g2_aliases.sh), reference in [`../docs/guides/shell-helpers.md`](../docs/guides/shell-helpers.md)), the git hooks and the docs link to them by name. Run Python tools from the repo root with `pi_pipeline/.venv/bin/python tools/<name>.py`; the ones that reach the Pi need `G2_PI` set.

## Documentation

| Tool | What it does |
|---|---|
| [`check_docs.py`](check_docs.py) | Doc checks: broken links, facts in the wrong page, orphan pages, stale generated pages. The pre-commit hook runs it. |
| [`gen_backlog.py`](gen_backlog.py) | Regenerates `docs/backlog.md` from the item headings. |
| [`gen_helpers_doc.py`](gen_helpers_doc.py) | Regenerates `docs/guides/shell-helpers.md` from the comments in `g2_aliases.sh`. |
| [`md_to_html.py`](md_to_html.py) | Turns one Markdown doc into a single self-contained HTML page. |
| [`make_petoi_edition.py`](make_petoi_edition.py) | Builds the English edition of the XiaoZhi and Petoi head documentation for sending to Petoi (reads [`docs/research/xiaozhi-vendor-docs.md`](../docs/research/xiaozhi-vendor-docs.md), writes outside the repo). |

## Running G2 from the Mac

| Tool | What it does | Guide |
|---|---|---|
| [`g2_aliases.sh`](g2_aliases.sh) | The `g2*` shell helpers (`g2`, `g2rl`, `g2pics`, `g2wifi`, …). `g2help` lists them. | [`shell-helpers.md`](../docs/guides/shell-helpers.md) |
| [`g2_deploy_when_online.sh`](g2_deploy_when_online.sh) | Waits for the Pi to answer, then `rsync`s `pi_pipeline/` and the deployed policy and restarts the voice service. Refuses during an exploration or a walk. | [`pi-bring-up.md`](../docs/guides/pi-bring-up.md) |
| [`g2_promote_policy.sh`](g2_promote_policy.sh) | Promotes a trained policy to the default and queues its deploy. | [`gait-deployment.md`](../docs/guides/gait-deployment.md) |
| [`g2_explore.sh`](g2_explore.sh) | Starts, stops and inspects a supervised exploration session on the Pi (the voice service always comes back). | [`exploration-mode.md`](../docs/guides/exploration-mode.md) |
| [`g2_safe_stop.sh`](g2_safe_stop.sh) | Rests G2, then stops whatever controls him. Never stop a controller any other way. | [`operating-g2.md`](../docs/guides/operating-g2.md) |
| [`g2_baseline.sh`](g2_baseline.sh), [`g2_turns.sh`](g2_turns.sh) | Logged baseline walks and firmware turn runs on the Pi. | [`rl/real-walk-log.md`](../docs/rl/real-walk-log.md) |
| [`g2_memory_backup.sh`](g2_memory_backup.sh) | Copies the Pi's memory database to this machine. | [`phase9-memory.md`](../docs/plan-detail/phase9-memory.md) |
| [`g2_wifi.sh`](g2_wifi.sh) | Manages the Wi-Fi networks the Pi joins. | [`pi-bring-up.md`](../docs/guides/pi-bring-up.md) |
| [`walk_log_summary.py`](walk_log_summary.py) | Summarizes walk logs from `run_gait.py` and the firmware-skill logger. | [`cheatsheet.md`](../docs/guides/cheatsheet.md) |
| [`servo_static_test.py`](servo_static_test.py), [`servo_response_test.py`](servo_response_test.py), [`servo_step_test.py`](servo_step_test.py) | Bench servo tests over the BiBoard's USB serial, using the firmware's position feedback. | [`servo-thermal.md`](../docs/hardware/servo-thermal.md) |
| [`g2_cleanup.py`](g2_cleanup.py) | Lists (and with `--apply` deletes) the scratch files that pile up on the Mac and the Pi. | [`docs/README.md`](../docs/README.md) |

## Real-data pipeline

How G2's own walk logs become sim calibration: [`docs/rl/real-data-pipeline.md`](../docs/rl/real-data-pipeline.md).

| Tool | What it does |
|---|---|
| [`g2_ingest.py`](g2_ingest.py) | Gates the Pi's automatic run logs into the real-data store (usable, quarantined, excluded; nothing deleted). |
| [`g2_calibrate.py`](g2_calibrate.py) | Builds numbered sim-calibration snapshots from the usable runs. |
| [`g2_cal_auto.sh`](g2_cal_auto.sh), [`g2_bg_jobs.sh`](g2_bg_jobs.sh) | The unattended calibration step and the 30-minute background loop that runs it with picture curation. |

## Vision dataset and pictures

The capture, curate, promote and upload flow: [`docs/guides/train-vision-model.md`](../docs/guides/train-vision-model.md), the routine in [`docs/vision/capture-checklist.md`](../docs/vision/capture-checklist.md), the on-camera model recipe in [`docs/vision/custom-model-recipe.md`](../docs/vision/custom-model-recipe.md).

| Tool | What it does |
|---|---|
| [`camera_preview.py`](camera_preview.py) | Live camera preview and on-demand capture for the Grove Vision AI V2. |
| [`curate_captures.py`](curate_captures.py) | Filters a raw capture batch into a training-ready set (score, de-dup, rotate, pre-label). |
| [`auto_process_captures.py`](auto_process_captures.py) | Runs everything after the manual capture step. |
| [`autobox_coco.py`](autobox_coco.py), [`interp_labels.py`](interp_labels.py) | Auto-label with a COCO detector; interpolate box labels for a slow-pan capture. |
| [`promote_to_library.py`](promote_to_library.py), [`optimize_library.py`](optimize_library.py), [`check_library_overlap.py`](check_library_overlap.py) | Promote a curated session into the library; balance it per class; flag near-duplicates. |
| [`combine_for_upload.py`](combine_for_upload.py), [`yolo_to_coco_zip.py`](yolo_to_coco_zip.py) | Build the upload set for SenseCraft. |
| [`person_filter.py`](person_filter.py) | Finds people in pictures locally so they stay out of the object library. |
| [`curate_exploration.py`](curate_exploration.py) | Curates the pictures G2 saved while exploring. |
| [`g2_curate_auto.sh`](g2_curate_auto.sh) | Keeps that exploration library curated without being asked. |
| [`g2_review.py`](g2_review.py) | The review page behind `g2pics` and `g2pimem`: name pictures, edit facts, undo wrong tags, with a Trash and Undo. |
| [`label_objects.py`](label_objects.py) | Reviews and labels the object-recognition gallery. |
| [`eval_embedder.py`](eval_embedder.py), [`eval_rooms.py`](eval_rooms.py) | Measure how well an embedder tells G2's pictures and rooms apart. |
| [`vision_diag.py`](vision_diag.py) | Runs the on-device detector through aggressive post-filtering to diagnose it. |
| [`gv2/`](gv2) | Model-export helpers for the camera: `export_yolov8_gv2.sh`, `split_yolo_dataset.py`, `vela_config_we2.ini`. |

## Training support

| Tool | What it does |
|---|---|
| [`eta.py`](eta.py) | Timing estimates for training runs, read from the trainer's logs (`plan`, `now`, `check`). Read-only. |
| [`build_decathlon_report.py`](build_decathlon_report.py) | Turns a decathlon result and its replays into a self-contained HTML report. |
| `v3_watchdog.sh`, `v4_watchdog.sh`, `v5_watchdog.sh`, `v6_watchdog.sh`, `hs_watchdog.sh` | Keep each training chain's runner alive unattended; each stops on its own halt file. Their chains are finished or stopped; see [`docs/rl/training-upgrade-2026-10.md`](../docs/rl/training-upgrade-2026-10.md). |

## Git hooks

[`githooks/`](githooks), enabled with `git config core.hooksPath tools/githooks`: `pre-commit` (docs check, leftover-file warning, large-commit block, privacy terms), `commit-msg` (strips attribution lines) and the `post-*` hooks that keep a local backup of `CLAUDE.md`.
