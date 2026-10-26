# Cheat sheet

The commands you actually run, grouped by what you are doing. Nearly everything is a `g2*` alias; the full list with every option is [`shell-helpers.md`](shell-helpers.md) (`g2help` prints it in the terminal). Safety rules before G2 moves: [`operating-g2.md`](operating-g2.md).

**Jump to:** [1 Setup](#1-setup) · [2 Day to day](#2-day-to-day) · [3 Stop and safety](#3-stop-and-safety) · [4 Test walks and logs](#4-test-walks-and-logs) · [5 Real data and calibration](#5-real-data-and-calibration) · [6 Pictures and memory](#6-pictures-and-memory) · [7 Camera and vision](#7-camera-and-vision) · [8 Voice](#8-voice) · [9 Training and policies](#9-training-and-policies) · [10 Bring-up and hardware](#10-bring-up-and-hardware) · [11 Docs and repo](#11-docs-and-repo) · [12 Things you say to G2](#12-things-you-say-to-g2)

## 1. Setup

Load the helpers once by adding this line to `~/.zshrc`, and set where the Pi is:

```bash
source /Users/markjohnson/Desktop/OneFolder/projects/bittleX/tools/g2_aliases.sh
export G2_PI=<user>@g2pi.local          # the Pi login; kept out of the repo
```

If the Mac sometimes cannot resolve `g2pi.local` while the Pi is up, run `bash tools/g2_pi_ssh_setup.sh` once: it adds a `Host g2pi.local` block to `~/.ssh/config` that falls back to the Pi's last known address (`tools/g2_pi_connect.sh`), still checking the Pi's host key, so every alias, deploy and tool keeps working. `--remove` takes it out.

Deploys (`tools/g2_deploy_when_online.sh`) ship the last commit, never uncommitted changes; the log lists anything under `pi_pipeline/` that was left out.

Every alias works from any directory and leaves you where you were, except `g2` and `g2rl`, which move you on purpose. In Claude Code, the `!` prefix runs each line in a fresh shell, so `source` and the alias must be on one line.

| Alias | Does |
|---|---|
| `g2` / `g2rl` | go to the repo with the pipeline venv / go to `rl_training/opencat-gym` with the RL venv |
| `g2back` | return to where you were before `g2` or `g2rl` |
| `g2help` / `g2docs` | list every helper / list the key docs |
| `g2ssh` | open a shell on the Pi |

## 2. Day to day

| Alias | Does |
|---|---|
| `g2reset` | restart the voice loop on the Pi (also ends an exploration session). `g2reset status` shows what is running, `g2reset logs` the recent log |
| `g2floor <label>` | set the floor G2 is on (`hardwood`, `tile`, `carpet`); every walk log records it. No argument shows it. **Set it before any walking run** |
| `g2explore start [secs]` | start a supervised exploration on the floor (asks the floor first if its label is unknown or over an hour old). `g2explore stop`, `status`, `logs`, `heard` (what the listener heard), `report` (the last roam's report and checks; `report html` opens the page) |
| `g2deploy` | push `pi_pipeline/` and the deployed policy to the Pi and restart the voice service. Waits for the Pi to answer; `g2deploy --once` deploys now. Refuses during an exploration or a walk. **Never deploy while testing** |
| `g2api [hours]` | Claude API calls and approximate cost on the Pi |
| `g2crash [n]` | why the voice service or an exploration crashed |
| `g2wifi list` | the Wi-Fi networks the Pi joins; `g2wifi add <ssid>` adds one |
| `g2membackup` | copy the Pi's memory database to the Mac |

## 3. Stop and safety

| What | How |
|---|---|
| Stop everything now | **say "emergency stop"** (also "freeze", "halt", "abort"); say "resume" to release |
| He is moving and nothing is in control | `g2rest` |
| Stop a service the safe way (rests him first) | `g2stop voice` or `g2stop explore`, never a plain service stop |
| Freeze or release an exploration session | `g2explore halt` / `g2explore release` |
| Work on the bench without autonomous movement | `g2app --bench` |

Never put G2 on his back; tests start on his feet with your hands near. More: [`operating-g2.md`](operating-g2.md), and the printable [`operating-g2-quick-guide.pdf`](operating-g2-quick-guide.pdf).

## 4. Test walks and logs

| Alias | Does |
|---|---|
| `g2walk [runs] [label]` | logged 12.5 s walks at 0.10 m/s with the deployed policy; the voice service is stopped for them and restarted after, and G2 tells you when to set him down |
| `g2baseline start|stop|status|logs|fetch` | the same walks with more options; `fetch` copies the logs to the Mac |
| `g2turns start|fetch` | logged firmware turn runs, to measure the real turn rate |
| `python pi_pipeline/gait/run_gait.py --openloop --base wkArm --cycles 6` | Petoi's arm walk played from the Pi, no policy (on the Pi; the arm build) |
| `g2walklog <log.csv>` | summarize a walk log: roll, pitch, yaw, the first fall, battery |
| `python -m pi_pipeline.diag report [SESSION | --kind explore] --html out.html` | one report for a session (on the Pi): walks, speech lag, wake triggers, API calls, camera timeouts, problems |
| `python -m pi_pipeline.attachments floor-trim tile fl=-0.1` | save a trim measured on one floor for the fitted attachment's gait (`off` removes it); used when `g2floor` is set and under 12 h old |
| `g2imu rest|stand [secs]` | record the raw IMU on the Pi and print its rate, bias and noise (stop the voice service first with `g2stop voice`) |

To walk by hand on the Pi (`g2stop voice` first, then `g2ssh`, then `cd ~/bittleX`):

```bash
pi_pipeline/.venv/bin/python pi_pipeline/gait/run_gait.py --cmd 0.10 --seconds 12.5 --log ~/g2_runs/x.csv
pi_pipeline/.venv/bin/python pi_pipeline/gait/run_gait.py --dry-run --seconds 5    # the loop with a synthetic IMU, no serial
```

Details: [`gait-deployment.md`](gait-deployment.md).

## 5. Real data and calibration

How G2's own walks become sim calibration: [`../rl/real-data-pipeline.md`](../rl/real-data-pipeline.md).

| Alias | Does |
|---|---|
| `g2data` | sync the Pi's logs, ingest them through the quality gates, show the status |
| `g2cal status` | the calibration snapshots; `g2cal show <id>` one in detail, `g2cal revert` undoes an automatic approval |
| `g2calauto` | run the whole calibration step now |
| `g2bg start|stop|status` | the Mac background loop (every 30 min): picture curation and calibration. It ends at a restart; run `g2bg start` again |

## 6. Pictures and memory

| Alias | Does |
|---|---|
| `g2pics` | the pictures G2 took while exploring, in a review page: name them, X to remove (Trash with Undo), promote to the training set. `g2pics pull` copies them from the Pi first |
| `g2picscurate` | curate the pulled pictures (lighting, sharpness, duplicates, people left out); the background loop does this too |
| `g2pimem` | G2's real memory on the Pi in the review page: facts, conversations, what he noticed. `g2pimem stop` ends it |
| `g2mem facts|log N|search <q>` | the same memory from the command line |

How the pictures flow: [`../vision/picture-library.md`](../vision/picture-library.md).

## 7. Camera and vision

| Alias | Does |
|---|---|
| `g2see` | live view with detection boxes from the camera on G2, at localhost:8080 |
| `g2vision` | print live detections from the camera over serial; `g2vision-demo` uses a mock feed |
| `g2walls` / `g2wallstats [days]` | the wall pictures; wall statistics from the Pi |
| `g2wallpic <label> <inches> [angle]` | take one labelled wall picture on the Pi (stop the voice service first) |
| `g2wallreplay` | what an exploring G2 would do with each saved wall picture; nothing moves |
| `python -m pi_pipeline.behavior.punt_test [--distances 2 3 4 5] [--repeat N]` | on the Pi (ssh -t), voice service stopped, G2 in rest: one punch (claw shut) at each ball distance, you place the ball and report how far it went; rows go to `~/g2_punt_tests.csv`. Dials in `PUNT_MAX_IN` in `behavior/ball_chase.py` |
| `python -m pi_pipeline.behavior.ball_chase [--dry-run] [--max-steps N]` | on the Pi, voice service stopped, G2 standing (arm fitted): chase the green treat ball and punt it with `kpickF` until stopped (`touch ~/.local/share/g2/ball_chase_stop` or Ctrl-C); `--dry-run` only prints what it would do. Its pictures with the ball found go to `g2pics` (Named: greenball). Read the battery percent first |

Building the camera's detection model (capture, curate, promote, upload to SenseCraft): capture with `g2pcam <name>` (the camera on G2, run on the Pi; `g2pcam-pull <name>` copies the session to the Mac) or `g2cam <name>` (a camera plugged into the Mac); `g2curate <name>` filters it, `g2promote <class>` adds it to the library, `g2auto` runs the rest and builds the upload set, `g2libstatus` shows the counts. Walkthrough: [`train-vision-model.md`](train-vision-model.md); capture routine: [`../vision/capture-checklist.md`](../vision/capture-checklist.md).

## 8. Voice

| Alias | Does |
|---|---|
| `g2chat` | talk to Claude by typing (needs the API key) |
| `g2voice` | the full voice loop on this machine: wake word, mic, speaker |
| `g2audio devices|wake|stt|tts` | audio diagnostics |
| `g2reset` | restart the voice loop on the Pi |
| `g2api [hours]` | what the voice loop has cost in API calls |
| `python -m pi_pipeline.voice.wake_log --days 7` | wake triggers: how many looked false, their confidence and words-before counts, and a suggested `G2_WAKE_MIN_CONF` |

The things you can say: [`voice-commands.md`](voice-commands.md). Settings and switches: [`settings-switches.md`](settings-switches.md).

## 9. Training and policies

Run from anywhere; the RL venv is used automatically. Rules for every run (a fresh candidate each time, never a 20M unasked, screens capped at 3M): [`../rl/training-pipeline.md`](../rl/training-pipeline.md).

| Alias | Does |
|---|---|
| `g2eta plan --steps 3e6 --tail stage` | a timing estimate before launching. During a run: `g2eta now --target 20e6 --tail final20m` |
| `g2train <tag>` | start a run with the pre-run checklist (the tag must be new) |
| `g2preflight` | must print ALL PASS before a 20M is offered |
| `g2watchrun` | watch the training run happening right now (it waits between a chain's stages). `g2watch` replays the newest finished policy. G2's real look needs `python build_body_mesh.py` once (looks only) |
| `g2tb` | open TensorBoard (`g2tb stop` ends it) |
| `g2rltest` | the RL test files. `g2test` is the pipeline suite |
| `g2policy <tag> <name>` | promote a trained policy to G2's default and arm the deploy (your call only). One attachment only: `python promote_release.py --candidate trained/X.onnx --name ARM1 --attachment arm --attachment-only --payload-profile arm` |

Score, export and check a policy, from `rl_training/opencat-gym` (`g2rl` takes you there):

```bash
python benchmark_decathlon.py --learned trained/<tag>_ppo --episodes 24 --hw i --json-out /tmp/dec.json   # the graded cells, through G2's real control path
python export_onnx.py --model trained/<tag>_ppo --residual-scale-deg 30 --cmd-send-every-n 3 --out trained/<tag>_ppo.onnx   # writes the .onnx and its .onnx.json sidecar
python validate_deploy.py --onnx trained/<tag>_ppo.onnx                                                    # must print ALL OK
```

## 10. Bring-up and hardware

| Alias | Does |
|---|---|
| `g2doctor [--serial]` | the readiness checklist: `.env`, API key, models, serial port, audio, disk |
| `g2bringup` | the guided, resumable hardware bring-up (`--list`, `--restart`, `--from <id>`) |
| `g2serial ports|ping|send <cmd>|skills|rest|firstmove|allmoves` | talk to the BiBoard; `firstmove` is the guided one-joint-at-a-time first movement |
| `g2app [--serial|--bench]` | the whole robot as one program (mock by default) |
| `g2power [status]` | the Pi power levers (a dry run unless run on the Pi) |
| `g2feat` / `g2traits` / `g2diag` | resolve feature flags / the personality traits / read a diagnostics session |

The BiBoard tokens worth knowing (send with `g2serial send <token>`; full reference: [`../hardware/petoi-firmware-reference.md`](../hardware/petoi-firmware-reference.md)):

| Token | Does |
|---|---|
| `d` | rest (servos relax) |
| `kbalance` | the calibration and stand pose; all four legs identical |
| `P` | battery voltage |
| `gc` | calibrate the IMU (G2 standing level and still); persists |
| `gb` / `gB` | firmware gyro balance off / on |
| `XS` | enable Serial-2 so the BiBoard listens to the Pi; once, redo after a reflash |
| `f` | servo position feedback stream (USB only) |

Never send `Xa` or `XAd`.

## 11. Docs and repo

| Alias | Does |
|---|---|
| `g2check` | the docs checks: broken links, facts in the wrong page, stale generated pages (the pre-commit hook runs it) |
| `g2docsgen` | regenerate the generated docs: backlog, shell-helpers, results index |
| `g2clean` | list scratch files on the Mac and Pi; `g2clean --apply` deletes them. Run before reporting a task done |
| `g2test` | the `pi_pipeline` test suite |
| `pi_pipeline/.venv/bin/ruff check` | lint, correctness rules only (the pre-commit hook runs it on staged `.py` files) |

Where each kind of change is written down: [`../README.md`](../README.md#where-to-update-what). `git commit --no-verify` bypasses the hooks for a genuine false positive.

## 12. Things you say to G2

Wake with "gee two". The full list and the conversational skills: [`voice-commands.md`](voice-commands.md).

| Say | Does |
|---|---|
| "emergency stop" / "resume" | freeze and hold / release |
| "gee two, let's talk" / "that's all" | conversation without the wake word until you stop |
| "go ahead and look around" / "end exploration mode" | start / end exploration |
| "come here" | walk to you |
| "hi step" / "walk normally" | switch gait |
| "the floor is tile" | set the floor label |
| "what do you see" | describe a picture |
| "go to sleep" / "shut down" | sleep / lie down and shut the Pi down (flip the PiSugar switch by hand after) |
