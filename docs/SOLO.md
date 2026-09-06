# Working on G2 solo

A launchpad for carrying the project forward without Claude. Points at the
detailed docs rather than repeating them.

---

## First-time setup

```
# 1. shell helpers (companion pipeline + camera). Add to ~/.zshrc:
source /Users/markjohnson/Desktop/OneFolder/projects/bittleX/tools/g2_aliases.sh
#    RL helpers (g2train, g2watch) are already in ~/.bash_profile.

# 2. two separate venvs:
g2      # cd repo + activate pi_pipeline/.venv   (companion pipeline, camera, tests)
g2rl    # cd rl_training/opencat-gym + activate .venv   (sim / training)

g2help  # list the companion-side helper commands
g2docs  # list the key docs
```

---

## What each thing is

| Piece | Where it runs | Notes |
|---|---|---|
| **RL gait policy** | trained in sim; deployed as ONNX on the Pi | frozen base = `run20m_ppo`. Training is paused pre-hardware. |
| **Vision model** | on the camera module's own chip | **one model at a time**; swap = reflash (~1–2 min). Only labels+boxes come out over serial. |
| **Companion pipeline** (`pi_pipeline/`) | the Pi | voice, memory, vision consumer, behaviour FSMs, serial link, diag, power. Runs mock-hardware on the Mac today. |
| **Bonds / personality** | the Pi, in the companion pipeline | disposition + closeness per recognised individual; drives greeting / approach / memory. |

Hardware status: Pi + camera in hand; **Bittle body + BiBoard are still weeks
out**, so anything needing the robot to move is bench-only for now.

---

## The task in progress: a face-recognition model

Full steps + commands: **`docs/train-a-visual-model.md`**. Short form:

```
g2cam-info                 # check the camera's connected + what model is loaded
g2cam alex 1               # capture session 1 -> preview at localhost:8080
#   ... run the pose sequence (docs/research/capture-session-checklist.md) ...
g2cam-stop
g2curate alex 1            # filter -> training set + pre-labels; prints the usable count
#   repeat for sessions 2 and 3 (different rooms / light)
g2combine alex             # gather all sessions -> upload/
#   ... upload to SenseCraft, label, train, deploy (train-a-visual-model.md steps 6-7) ...
g2vision alex              # verify the deployed model over serial
```

Then in `.env`: add the name to `VISION_LABELS` and `G2_BONDS`.

**The bar** (learned the hard way 2026-09-06): 80–120+ varied, well-lit images
per person across 3 sessions. Dark / few / one-condition = a model that detects
nothing.

---

## Common operations

| Want to... | Do |
|---|---|
| See live camera detections | `g2vision person` (or your class list) |
| Talk to G2 (text) | `g2chat` — needs `ANTHROPIC_API_KEY` in `.env` |
| Full voice loop | `g2voice` — needs audio deps + models (`pi_pipeline/voice/README.md`) |
| Inspect / edit G2's memory | `g2mem facts` · `g2mem log 30` · `g2mem search "cat"` · `g2mem wipe --yes` |
| See which subsystems are enabled | `g2feat` · bring-up stages: `g2feat --profiles` |
| Resolve personality traits | `g2traits "curiosity=0.9"` |
| Talk to the BiBoard (on hardware) | `g2serial ports` → `g2serial ping` → `g2serial skills` |
| Read a diagnostics session | `g2diag list` → `g2diag summarize <sid>` |
| Run the test suite | `g2test` |
| Watch a gait in sim | `g2rl` then `python watch.py --challenge slope-up` (see `cheatsheet.md`) |

---

## Gotchas

- **Serial port is single-owner.** SenseCraft's in-app "disconnect" does NOT
  free it — **close the SenseCraft browser tab** (or unplug/replug USB) before
  any `g2cam*` / `g2vision` command. Symptom: "Resource busy" / `lsof` shows
  Google Chrome.
- **Camera orientation.** The sensor's native feed is 90°-rotated. Physically
  rotate the module so the *raw* preview (rotate-view back to 0°) is upright —
  otherwise the person detector misses you and you get few pre-labels. That
  rotation is also the mount orientation for G2. Curate's `--rotate` (90/180/
  270) makes the saved files upright; the contact sheet shows if it's wrong.
- **Low light.** `g2cam` already sets 480 capture + an auto-exposure lift
  (`docs/research/vision-detector-bench.md`). Past that it's real light — add
  lamps. Brighter = longer exposure = more motion blur, so hold still on poses.
- **A trained model that detects nothing** = the dataset was too weak. Recapture
  brighter / more / more varied and retrain — it's free and fast.
- **Feature flags.** `G2_FEATURES=profile:p2-gait` etc. restrict what starts, for
  isolating bugs during bring-up. Empty = everything on. See
  `docs/feature-flags.md`.

---

## Do carefully / ask first

- **Pushing to the remote.** Commit locally freely; `git push origin
  development` is a deliberate step — the repo is **public**, and the
  pre-commit hook blocks personal terms (your SenseCraft name included), so use
  placeholders in tracked files.
- **A from-scratch ~20M gait run.** Gated on the green-light checklist
  (`docs/rl-runs/hardware-gated-training-backlog.md` + `project_longrun_trigger`
  memory). The 2026-09-05 new-course run was a negative result — `run20m_ppo`
  stays the base.
- **Deleting capture folders / `trained/` checkpoints / the memory DB.** Look
  first; they're not all reproducible.

---

## Where the deeper docs are

| Topic | Doc |
|---|---|
| Camera-model training, end to end | `docs/train-a-visual-model.md` |
| Capture routine (per session) | `docs/research/capture-session-checklist.md` |
| Recognition design + "G2, meet X" enrollment | `docs/research/person-recognition.md` |
| One-slot / multi-model detection architecture | `docs/research/detection-layer.md` |
| Measured module behaviour + AE-lift finding | `docs/research/vision-detector-bench.md` |
| Staged bring-up flags | `docs/feature-flags.md` |
| Day-1 hardware checklists | `docs/hardware-readiness.md` |
| RL/gait history + backlog | `docs/rl-runs/` |
| Everything else | `docs/project-plan.md`, `docs/how-it-works.md` |
| All commands | `docs/reference/cheatsheet.md`, `docs/reference/commands.md` |
