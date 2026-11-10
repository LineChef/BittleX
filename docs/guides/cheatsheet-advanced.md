# Cheat sheet: setup, training, bring-up and repo

The commands you run rarely. The everyday ones are on [`cheatsheet.md`](cheatsheet.md); every option of every alias is in [`shell-helpers.md`](shell-helpers.md).

**Jump to:** [Setup](#setup) · [Pi commands](#commands-on-the-pi) · [Training](#training-and-policies) · [Bring-up](#bring-up-and-hardware) · [Board tokens](#board-tokens) · [Camera model](#camera-model) · [Docs and repo](#docs-and-repo) · [A to Z](#a-to-z)

## Setup

Add this to `~/.zshrc` once, and set where the Pi is:

```bash
source /Users/markjohnson/Desktop/OneFolder/projects/bittleX/tools/g2_aliases.sh
export G2_PI=<user>@g2pi.local          # the Pi login; kept out of the repo
```

If the Mac sometimes cannot find `g2pi.local` while the Pi is up, run this once. It adds an `~/.ssh/config` block that falls back to the Pi's last known address; add `--remove` to undo it:

```bash
bash tools/g2_pi_ssh_setup.sh
```

Every alias works from any directory and leaves you where you were, except `g2` and `g2rl`. In Claude Code, `!` runs each line in a fresh shell, so `source` and the alias must be on one line.

| Command | Does |
|---|---|
| `g2` | go to the repo with the pipeline venv |
| `g2rl` | go to `rl_training/opencat-gym` with the RL venv |
| `g2back` | return to where you were |
| `g2help` | list every helper |
| `g2docs` | list the key docs |
| `g2ssh` | open a shell on the Pi |

## Commands on the Pi

Run these over `g2ssh` from `~/bittleX`, with the voice service stopped (`g2stop voice`) and G2 standing.

| Command | Does |
|---|---|
| `pi_pipeline/.venv/bin/python pi_pipeline/gait/run_gait.py --cmd 0.10 --seconds 12.5 --log ~/g2_runs/x.csv` | one logged policy walk |
| `pi_pipeline/.venv/bin/python pi_pipeline/gait/run_gait.py --dry-run --seconds 5` | the loop with a synthetic IMU, no serial |
| `python pi_pipeline/gait/run_gait.py --openloop --base wkArm --cycles 6` | Petoi's arm walk, no policy |
| `python -m pi_pipeline.diag report --html out.html` | one report for a session |
| `python -m pi_pipeline.attachments floor-trim tile fl=-0.1` | save a trim measured on one floor |
| `python -m pi_pipeline.behavior.ball_chase --dry-run` | print what the chase would do |
| `python -m pi_pipeline.behavior.punt_test --distances 2 3 4 5` | one punch at each ball distance |
| `python -m pi_pipeline.behavior.wall_settings --set chase_wall_in 10` | your own wall settings |
| `python -m pi_pipeline.voice.wake_log --days 7` | wake triggers, false ones, suggested confidence |
| `python -m pi_pipeline.power runtime test start` | a timed Pi battery-life test |

Details: [`gait-deployment.md`](gait-deployment.md), [`punt.md`](punt.md), [`goals.md`](goals.md).

## Training and policies

Run from anywhere; the RL venv is used automatically. Rules: [`../rl/training-pipeline.md`](../rl/training-pipeline.md). A fresh candidate each run, never a 20M unasked, screens capped at 3M.

| Command | Does |
|---|---|
| `g2eta plan --steps 3e6 --tail stage` | a timing estimate before launching |
| `g2eta now --target 20e6 --tail final20m` | the estimate during a run |
| `g2train mytag` | start a run with the pre-run checklist (new tag) |
| `g2preflight` | must print ALL PASS before a 20M |
| `g2watchrun` | watch the run happening now |
| `g2watch` | replay the newest finished policy |
| `g2tb` | open TensorBoard (`g2tb stop` ends it) |
| `g2rltest` | the RL test files |
| `g2test` | the pipeline test suite |
| `g2policy mytag Release_Candidate` | promote a policy to G2's default (your call only) |

Score, export and check a policy from `rl_training/opencat-gym` (`g2rl` goes there):

```bash
python benchmark_decathlon.py --learned trained/<tag>_ppo --episodes 24 --hw i --json-out /tmp/dec.json
python export_onnx.py --model trained/<tag>_ppo --residual-scale-deg 30 --cmd-send-every-n 3 --out trained/<tag>_ppo.onnx
python validate_deploy.py --onnx trained/<tag>_ppo.onnx            # must print ALL OK
python promote_release.py --candidate trained/X.onnx --name ARM1 --attachment arm --attachment-only --payload-profile arm
```

## Bring-up and hardware

| Command | Does |
|---|---|
| `g2doctor --serial` | readiness checklist: key, models, serial, audio, disk |
| `g2bringup` | guided, resumable hardware bring-up |
| `g2serial ports` | list serial ports |
| `g2serial ping` | is the BiBoard answering |
| `g2serial firstmove` | guided first movement, one joint at a time |
| `g2serial allmoves` | full movement sweep |
| `g2app --serial` | the whole robot as one program |
| `g2feat` | resolve the feature flags |
| `g2traits` | resolve the personality traits |
| `g2diag` | read a diagnostics session |
| `g2attach arm` | tell the Pi what G2 is wearing (head, arm, none) |

### Board tokens

Send with `g2serial send <token>`. Full reference: [`../hardware/petoi-firmware-reference.md`](../hardware/petoi-firmware-reference.md). **Never send `Xa` or `XAd`.**

| Token | Does |
|---|---|
| `d` | rest (servos relax) |
| `kbalance` | calibration and stand pose |
| `P` | battery voltage |
| `gc` | calibrate the IMU (level and still) |
| `gb` / `gB` | firmware gyro balance off / on |
| `XS` | enable Serial-2 (once; redo after a reflash) |
| `f` | servo feedback stream (USB only) |

## Camera model

Build the detection model: capture, filter, add to the library, upload to SenseCraft. Walkthrough: [`train-vision-model.md`](train-vision-model.md); routine: [`../vision/capture-checklist.md`](../vision/capture-checklist.md).

| Command | Does |
|---|---|
| `g2pcam mug` | capture with the camera on G2 |
| `g2pcam-pull mug` | copy that session to the Mac |
| `g2cam mug` | capture with a camera plugged into the Mac |
| `g2curate mug` | filter the session |
| `g2promote mug` | add the class to the library |
| `g2auto` | run the rest and build the upload set |
| `g2libstatus` | the library counts |

## Docs and repo


| Command | Does |
|---|---|
| `g2check` | docs checks (the pre-commit hook runs it) |
| `g2docsgen` | regenerate the generated docs |
| `g2clean` | list scratch files; `g2clean --apply` deletes them |
| `g2test` | the `pi_pipeline` test suite |
| `pi_pipeline/.venv/bin/ruff check` | lint (the pre-commit hook runs it) |

`git commit --no-verify` bypasses the hooks for a genuine false positive.

## A to Z

The A to Z of every command is at the bottom of [`cheatsheet.md`](cheatsheet.md#a-to-z).
