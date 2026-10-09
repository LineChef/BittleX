# Command Cheat Sheet

The single command reference for the project, **grouped by task** — quick tables and the full step sequences (RL runs by hand, env
setup). Add to it by telling me "add this to the cheat sheet"; put a command in the group where you would look for it.

**Find it:** [1 Setup and everyday](#1-setup-and-everyday) · [2 The robot: run, stop, safety](#2-the-robot-run-stop-safety) ·
[3 BiBoard serial and firmware tokens](#3-biboard-serial-and-firmware-tokens) · [4 Walking the real robot](#4-walking-the-real-robot) ·
[5 Deploying to the Pi](#5-deploying-to-the-pi) · [6 Camera and vision](#6-camera-and-vision) ·
[7 Voice, memory and config](#7-voice-memory-and-config) · [8 Simulation and RL](#8-simulation-and-rl) · [9 Quick checks and git](#9-quick-checks-and-git)

Shell helpers: RL (`g2train`, `g2watch`) in `~/.bash_profile`; companion + camera helpers (`g2cam`, `g2see`, `g2pcam`, …) in
`tools/g2_aliases.sh`. Every companion alias except `g2` / `g2rl` runs from any directory and leaves your cwd unchanged. RL commands
run from `rl_training/opencat-gym/`. The `!` prefix in Claude Code runs each line in a fresh shell, so `source` and `g2*` on separate lines
won't work — use one line (`source …/g2_aliases.sh && g2see`) or your own Terminal.

---

## 1. Setup and everyday

Load the helpers once (add to `~/.zshrc`): `source /Users/markjohnson/Desktop/OneFolder/projects/bittleX/tools/g2_aliases.sh`.
`g2help` prints the list; [`SOLO.md`](SOLO.md) is the solo-operation guide.

| Command | Does |
|---|---|
| `g2` | cd repo + activate `pi_pipeline/.venv` |
| `g2rl` | cd `rl_training/opencat-gym/` + activate the RL `.venv` |
| `g2test` | run the `pi_pipeline` test suite |
| `g2back` | return to the directory you were in before `g2` / `g2rl` |
| `g2help` | list these helpers · `g2docs` list the key docs |
| `export G2_PI=<user>@g2pi.local` | in `~/.zshrc`: the Pi login the `g2see` / `g2pcam` aliases use (kept out of the repo) |
| `python tools/check_docs.py` | doc checks: broken links, hard-coded test counts, the deployed policy name in the wrong page (runs in the pre-commit hook; `--staged` = staged files only) |
| `python tools/gen_backlog.py` | regenerate `docs/backlog.md` after changing an item's status heading (`--check` to verify) |
| `git commit --no-verify` | bypass the hooks for a genuine false positive |

Where each kind of change gets written down: [`../README.md`](../README.md#where-to-update-what).

## 2. The robot: run, stop, safety

| Command | Does |
|---|---|
| `python -m pi_pipeline.doctor` | **bring-up readiness checklist** — `.env`, API key + expiry, model files, deps, serial port, audio, disk. `--serial` also pings the board. Non-zero exit on any hard FAIL |
| `python -m pi_pipeline.app` | the whole robot — voice loop + behaviour runtime, side by side. Mock by default; `--serial` talks to the BiBoard |
| `python -m pi_pipeline.app --bench` | **stand/bench mode** — no autonomous movement, voice actuator = mock. Use while running calibration / `check_serial` / `--probe-imu` |
| `python -m pi_pipeline.app --halt` / `--release` | **EMERGENCY STOP** a running app (freeze + hold) / clear it. Also `kill -USR1 <pid>` / `-USR2`, or _say_ "emergency stop" / "freeze" / "resume" |
| `python -m pi_pipeline.behavior` | behaviour runtime alone vs mocks — prints the effect stream (idle → sit → rest → sleep → wake) |
| `python -m pi_pipeline.bringup` | **guided, resumable bring-up checklist** — the 20-step hardware sequence (Phase 0 bare hardware → Phase 1+ with the Pi wired in, stand-only through step 13a; 13b is the first floor test, gated by an explicit confirm), one step at a time. `--list` / `--restart` / `--from <id>` |
| `python -m pi_pipeline.app --trace <path>` | log every serial command sent to a timestamped file |
| `python -m pi_pipeline.link.trace replay <path> [--dry-run]` | replay a trace at the same relative pacing |
| `g2power [status\|headless\|interactive\|governor <n>]` | Pi power-management helpers |

## 3. BiBoard serial and firmware tokens

The BiBoard's serial tokens worth remembering (full reference: [`../hardware/petoi-firmware-reference.md`](../hardware/petoi-firmware-reference.md)).
Servo numbers: 8, 9, 10, 11 = FL, FR, BR, BL shoulders; 12–15 = the same order for the knees. Send with `check_serial send <token>` / `g2serial send <token>`, or
over the Mac's USB cable.

| Command | Does |
|---|---|
| `g2serial [ports\|ping\|send <cmd>\|skills\|rest\|firstmove\|allmoves]` | BiBoard serial link checks; `firstmove` = guided one-joint-at-a-time first movement (confirmed, always ends at rest); `allmoves` = cycles every known move (skills + gestures + sleep + carpet gait + recovery keyframes), logging voltage + reply latency per move to diag |
| `XS` | enable Serial-2 so the BiBoard listens on the Pi's UART — **once**; it persists, redo after any reflash/erase |
| `X?` | print the module table (`S,A,T,…` and a `0/1` row); plain `?` prints only the name and version |
| `gc` | calibrate the IMU — G2 standing level and still; the body rocks for several seconds and no reply prints; persists, redo after a reflash |
| `gb` / `gB` | firmware gyro balance **off** / **on** (bare `g` toggles — avoid) |
| `kbalance` | the calibration / stand pose, all four legs identical — with balance off it should read level |
| `P` | battery voltage (`Voltage: 7.8 V`; ~8.4 V is full for the 2-cell pack) |
| `f` | servo position feedback: a stream of 8 values (servos 8–15), ~5 rows/s. **USB only** (the Pi UART only echoes); any new command stops it, so restart with `f` |
| `i8 50 12 0 9 50 13 0 10 50 14 0 11 50 15 0` | the policy's stand pose (shoulders 50°, knees 0°) as one simultaneous move; `i<servo> <deg>` moves one joint |
| `b16 10 12 12` | chirp — G2 beeps if the Pi→BiBoard path works |
| `d` | rest (servos relax) |

Mac USB cable: **plug it in** for feedback / servo tests, **unplug it** for untethered walks (it tethers G2 and the Pi UART is the real link).

## 4. Walking the real robot

Pi side, from `~/bittleX` (`pi_pipeline/.venv`). Logs go to `~/g2_runs/` on the Pi. Never put G2 on its back for a test.

| Command | Does |
|---|---|
| `python bench_real.py` | Time the real `run20m_ppo.onnx` end-to-end (ONNX + obs build) — the per-tick cost |
| `python run_gait.py --dry-run --seconds 5` | Full 80 Hz loop, synthetic IMU, no serial — rate check |
| `python run_gait.py --probe-imu` | Print raw BiBoard `V` IMU stream — check `parse_imu_line` matches the format |
| `python run_gait.py --openloop` | Play `wkf_ref.npy` open-loop (on a cradle) — verify servo signs, set `deploy_map.SERVO_SIGN` |
| `python run_gait.py --cmd 0.10` | The learned gait on the real robot (firmware balance off) |
| `python run_gait.py --cmd 0.10 --keep-firmware-balance --log run.csv` | + firmware gyro-assist underneath, logging per-tick for `sysid_replay` |
| `python run_gait.py --cmd 0.10 --carpet` | + carpet-slip detector (BOOST_CMD / `kcarpetF` hand-off). Inert until body-X accel is plumbed through `parse_imu_line` + thresholds tuned on real carpet |
| `python sysid_collect.py --log sysid.csv` | Policy-free calibration sequence (loaded poses + slow wkF) → log for `sysid_replay` |
| `python h1_score.py --template > runs.json` then `python h1_score.py --from runs.json` | Score the H1 head-to-head from measured numbers → verdict |
| `python pi_pipeline/gait/run_gait.py --cmd 0.10 --seconds 12.5 --log ~/g2_runs/x.csv` | the deployed policy for ~10 gait cycles, logged. The fall guard (`--fall-abort-deg`, default 60°) rests G2 if it goes over. The policy's send cadence follows its sidecar; `--policy <onnx>` and `--send-every N` override |
| `python pi_pipeline/gait/run_gait.py --openloop --cycles 6 [--lift-scale K --lift-joints knees --shoulder-scale S --ramp-cycles 1 --openloop-balance-off --volt-every 0.5 --log x.csv]` | scripted `wkF` playback with optional lift/stride scaling, a ramp-in, battery logging and IMU logging |
| `python pi_pipeline/gait/fw_skill_log.py kcarpetF --seconds 10 --log x.csv` | run a firmware gait for N seconds with IMU logging, then rest |
| `g2gait [--dry-run\|--openloop\|...]` | the on-robot gait control loop |

Analyze runs (dev machine):

| Command | Does |
|---|---|
| `scp $G2_PI:g2_runs/<file>.csv ~/g2_runs/` | copy a run log off the Pi (the robot never needs to plug into the Mac for logs) |
| `python tools/walk_log_summary.py <csv…>` | summarize logs: roll/pitch/yaw, the first fall, battery voltage |
| `python tools/servo_static_test.py [--out x.csv]` | per-joint offset and gain from servo feedback — G2 standing, balance off, **Mac USB plugged in** |
| `python tools/servo_response_test.py` | stand↔rest and shoulder-step feedback (caution: it cuts moves short; see its docstring) |
| `python sim_vs_real_walk.py [logs]` | replay real logs open-loop in the sim and compare roll/pitch/distance (from `rl_training/opencat-gym/`, RL venv) |
| `python sysid_replay.py --log <real_log.csv>` | Replay a real robot log's joint commands open-loop in a sim mirror; report the sim-to-real tilt/rate gap |
| `python sysid_replay.py --log <real_log.csv> --fit` | + sweep motor force / PD gains / `CMD_LATENCY_STEPS` to close the gap; prints the env edits |

## 5. Deploying to the Pi

Deploying is `rsync`, never `git clone` ([`pi-bring-up.md`](pi-bring-up.md) §7, [`gait-deployment.md`](gait-deployment.md)).

| Command | Does |
|---|---|
| `rsync -az --delete --exclude .venv --exclude __pycache__ --exclude .pytest_cache pi_pipeline/ $G2_PI:~/bittleX/pi_pipeline/` | push the Pi code — the excludes protect the Pi's own venv |
| `rsync -az rl_training/opencat-gym/trained/<policy>_ppo.onnx rl_training/opencat-gym/trained/<policy>_ppo.onnx.json $G2_PI:~/bittleX/rl_training/opencat-gym/trained/` | push a policy **and** its sidecar |
| `bash pi_pipeline/setup_pi.sh` | one-shot idempotent Pi OS setup (run on the Pi over SSH) |
| `bash pi_pipeline/fetch_models.sh` | download the Vosk / Piper models into `./models/` |
| `python -m pi_pipeline.benchmark_pi [--skip-api] [--skip-stress]` | full voice-pipeline benchmark on the Pi |
| `python export_onnx.py --model trained/<run>_ppo --cmd-send-every-n 3` | export with the command cadence recorded in the sidecar (the Pi loop follows it) |

Mac side, from `rl_training/opencat-gym/`:

| Command | Does |
|---|---|
| `python export_onnx.py --model trained/run20m_ppo --out trained/run20m_ppo.onnx` | Export the deterministic policy to ONNX (drops value net + noise) |
| `python export_onnx.py --model trained/<run>_ppo` | Export a policy: writes `<run>_ppo.onnx` **and** the `.onnx.json` sidecar with its residual scale (ship both to the Pi) |
| `python verify_onnx.py --model trained/run20m_ppo --onnx trained/run20m_ppo.onnx` | Parity check: ONNX vs PyTorch actions across gaussian + a real rollout |
| `python validate_deploy.py` | Drive `pi_pipeline/gait/residual_policy.py` from the sim in lockstep with `model.predict` — asserts obs + joint targets match bit-for-bit |
| `python validate_deploy.py --onnx trained/<run>_ppo.onnx` | Same check for a specific policy — must print `residual scale: <N> deg` from its sidecar and `ALL OK` |
| `python resilience_imu_rate.py` / `python resilience_joint_cmd.py` | What the stock 5 Hz IMU / the `m` vs `i` joint command cost the deployed policy in sim |

## 6. Camera and vision

Full walkthroughs: [`train-vision-model.md`](train-vision-model.md), [`../vision/capture-checklist.md`](../vision/capture-checklist.md),
[`../vision/capture-progress.md`](../vision/capture-progress.md) (the multi-class capture library; point capture at the raw root first:
`export G2_CAP_ROOT=~/Desktop/g2_capture_raw`).

**Look at / capture from the camera mounted on G2** (plugged into the Pi; needs `G2_PI`)

| Command | Does |
|---|---|
| `g2see` | **just look** -- live feed with detection boxes from the camera mounted on G2 (plugged into the Pi) at `localhost:8080`; no name, nothing saved. Close the tab to stop (or `g2pcam-stop`). Needs `G2_PI` exported; tells you if the camera isn't plugged in |
| `g2pics [open\|status\|pull\|stop]` | **the pictures G2 saved while exploring, as large uncropped thumbnails in the review page (click one to enlarge; a "cut off" badge marks pictures the camera module cut short)** (survey stops and objects you named; an X on each moves it to the Trash with Undo; Trash tab restores; "Empty trash" is the only permanent delete and asks twice). Runs in the background, opens `http://127.0.0.1:8765`; `status` = text summary from the Pi, `pull` = copy to `~/g2_pictures/explore`, `stop` = end the page. Only near-duplicates are ever deleted automatically. |
| `g2pcam <name> [session]` | preview/capture with the camera **mounted on G2** (plugged into the Pi): runs `camera_preview.py` on the Pi, tunnels it to `localhost:8080`, opens it. Saves on the Pi in `~/g2_cap/<name>/session_<n>/`. Closing the tab stops it. Needs `export G2_PI=<user>@g2pi.local` in your shell profile |
| `g2pcam-pull <name> [session]` | copy that Pi capture to `$G2_CAP_ROOT/<name>/session_<n>/` so `g2curate` / `g2auto` work on it as usual |
| `g2pcam-stop` | kill the tunnel and the preview process on the Pi |
| `g2membackup` | copy the Pi's memory DB (conversation log + facts) to the Mac, integrity-checked; lands outside the repo in `$G2_BACKUP_DIR` (default `~/Desktop/OneFolder/G2/memory-backups`). Needs `G2_PI` |
| `g2wifi list` / `status` / `scan` / `add <ssid>` / `remove <ssid>` | manage the Wi-Fi networks the Pi auto-joins. `add` asks for the password and saves the network as a backup (priority 50, below home's 100), so away from home the Pi joins e.g. your phone hotspot by itself. Do the `add` while the Pi is still reachable. Needs `G2_PI` |

**Camera plugged into the Mac**

| Command | Does |
|---|---|
| `g2cam <name> [session]` | start the live capture preview at `localhost:8080`, saving to `~/Desktop/g2_face_capture/<name>/session_<n>/` |
| `g2cam-stop` | stop the preview (`pkill -f camera_preview.py`) |
| `g2cam-info` | print the serial port + which model is on the module |

**Curate captures and build the model library**

| Command | Does |
|---|---|
| `g2curate <name> [session] [rotate]` | filter a raw capture → `<session>/curated/` (score, de-dup, rotate upright, YOLO pre-labels); prints usable count + running total. `rotate` default 0 |
| `g2combine <name>` | gather every session's `curated/` into `<name>/upload/` (per-session subdirs) |
| `g2promote <class> [session]` | copy a reviewed `curated/` session into the persistent library `~/Desktop/g2_vision_library/<class>/`, updating `_MANIFEST.md` |
| `g2libcombine [classes]` | build `~/Desktop/g2_vision_library/upload/` from the library (default `person,dog,cat,ledge`); rewrites label class-ids from the class order |
| `g2libstatus` | print the library `_MANIFEST.md` (per-class counts) |

**Vision runtime**

| Command | Does |
|---|---|
| `g2vision [labels]` | run the detection pipeline over serial, print live detections. e.g. `g2vision person,alex` |
| `g2vision-demo` | mock detection feed, no hardware |
| `g2visioneval [label] [secs]` | timed measurement — detection rate / confidence / p10 floor / flicker + VERDICT (for the dataset-size threshold test). 3rd arg `empty` + clear scene → false-fire check |

**Raw (no alias)**

| Command | Does |
|---|---|
| `python tools/curate_captures.py --help` | all curate flags |
| `python tools/camera_preview.py --info` | port + loaded model, no server |
| `ssh -L 8080:127.0.0.1:8080 $G2_PI 'G2_CAP_OUT=~/g2_cap ~/bittleX/pi_pipeline/.venv/bin/python ~/bittleX/tools/camera_preview.py'` | what `g2pcam` does under the hood; open `localhost:8080` within 10 s or the preview stops itself. The Pi's camera is `/dev/ttyACM0` |

## 7. Voice, memory and config

**Voice / conversation**

| Command | Does |
|---|---|
| `g2chat` | text conversation with Claude (needs `ANTHROPIC_API_KEY`) |
| `g2voice` | full voice loop — wake word + mic + Piper TTS (needs audio deps + models) |
| `g2audio [devices\|wake\|stt\|tts]` | audio diagnostics |
| `python -m pi_pipeline.voice.livecheck` | real-API end-to-end check: reply + `perform_skill`/`remember` parsing + memory seam (needs a key; ~4 billed calls) |
| _say_ "shut off" / "turn off" (bare phrases only) | same as "shut down" above; "turn off the music" does not trigger it |
| _say_ "you're unplugged" / "you're plugged in" | start / pause the Pi-battery runtime count (the PiSugar S has no telemetry, so G2 only warns while counting) |
| _say_ "go ahead and look around" / "exploration mode" / "explore" (to the normal voice service) | hands over to an exploration session (about 5 s after he answers): the voice service stops, G2 roams for up to 10 minutes (`G2_EXPLORE_ROAM_S`), then the voice service starts again by itself; "that's enough" ends it early. `G2_EXPLORE_HANDOVER=0` turns the hand-over off |
| `bash tools/g2_explore.sh heard [N]` | the last N (25) things the exploration listener logged: wake words, nothing recognized, what was heard, naming requests, pictures saved. Use it to see whether a voice command registered. |
| `bash tools/g2_explore.sh start [ROAM_S]` / `arm` / `disarm` / `halt` / `release` / `stop` / `status` / `logs` | supervised exploration test on the floor: stops `g2-voice`, runs the behavior runtime with narration (Tier 0 stationary from the start, Tier 1 roam on `arm` or by voice, roam capped at ROAM_S, default 600 s = 10 min, 0 = no cap; session ends after 2 h). Voice after the wake word: "emergency stop", "resume", "go ahead and look around", "that's enough", "tell me what you see" (the detector's view, no API call), "shut down" (ends the session only), and ALWAYS restarts `g2-voice` when it ends. No edge detector: never on a desk or the stand. Needs `G2_PI` |
| `G2_DEFAULT_GAIT=firmware` in the Pi's `.env` | go back to the stock scripted `wkF` for forward walking (default `policy` = the deployed learned V2.1 walk, for voice `walk_forward` and exploring) |
| `G2_LOG_HEARD=1` in the Pi's `.env` | log every transcript the speech recognizer produced (`journalctl -u g2-voice \| grep heard:`) |
| `cat ~/.local/share/g2/battery_voltage.csv` (on the Pi) | G2's pack voltage history, one line per 5 minutes (`G2_BATTERY_LOG`, `G2_BATTERY_LOG_EVERY_S`; empty path = off) |
| `G2_STT_COMMAND_GRAMMAR=0` in the Pi's `.env` | turn off the second recognizer that rescues misheard stop / shut-down commands |
| `python -m pi_pipeline.benchmark_pi --skip-api` | RAM / Piper synth / Vosk transcribe timings + Piper→Vosk recall (run on the Pi) |
| _say_ "enable gir mode" / "disable gir mode" / "set gir to 70" | toggle the opt-in character mode at runtime (persists to `character.json`, outranks `G2_CHARACTER`) |
| _say_ "end exploration mode" (or "cancel exploration mode") (also "end explore mode", "exit exploration mode", "stop exploration mode") | **ends the exploration session** and brings the normal voice service back; no emergency stop involved (use this instead of "freeze" when you only want to end the test) |
| _say_ "go ahead and look around" / "exploration mode" ⟷ "that's enough" / "come back" | arm / disarm **Tier 1 roam** (walking explore — voice-armed only; leg-budget leash; audible "roaming" chirp; disarms on exit). Tier 0 "attentive" (stationary sound-turn + gaze-follow-with-satiation + reactions) is always on |
| _say_ "come here" / "come to me" | **directed walk toward you** (`Mode.APPROACH`) — stops close, gives up (confused chirp) if it loses sight. Distinct from "come back" |
| _say_ "shut down" / "power down" / "power off" (a short, clear command) | **lies G2 down AND shuts the Pi down cleanly** (`sudo shutdown -h now`): he says he will switch the computer off in 6 s and you can say **"cancel"** (or stop / wait / no / never mind) to keep it on, then "Goodbye." and the Pi powers down. A longer or unclear sentence ("shut down but not the whole computer...") keeps the old behavior: lie flat (`d`), hold ~2 s, go dormant (power-save, camera off). **Verified 2026-10-05: the PiSugar S keeps powering the Pi after it halts, so flip its switch off by hand** (G2 says so in his goodbye). `G2_POWEROFF_ON_SHUTDOWN=0` turns the OS shutdown off; `G2_SHUTDOWN_CONFIRM_S` sets the cancel window. "go to sleep" is the lighter curl variant; "emergency stop" is the freeze | 

**Memory / config / diagnostics**

| Command | Does |
|---|---|
| `g2mem [facts\|log N\|search q\|recall q\|export [--scrub]\|wipe --yes]` | inspect / edit G2's memory (CLI) |
| _say_ "this is the dishwasher" / "this is my red mug" / "remember this as the mug" / "call this the mug" (wake word first; **works in plain voice mode and inside an exploration session**) | **name an object**: he bows, looks up, stands, then takes one picture saved under that name (`g2pics` shows them under Named), and says "Okay, I will remember the X". Needs the object in view about 30 to 60 cm ahead; name it from several angles and distances (aim for 5 or more); no Claude call. |
| `g2data [sync\|ingest\|status]` | **G2's automatic run logs on the Mac**: `sync` copies the Pi's run and detection logs to `~/g2_data`; `ingest` measures every run, applies the quality gates (complete, fit-ok hardware epoch, known floor, long enough, loop on time, IMU fresh, no fall or collision, not an outlier) and stores it gzip-compressed with nothing deleted (a run that fails is quarantined with its reasons); `status` shows usable runs by hardware epoch, floor and pack voltage. No argument = all three. |
| `g2reset [status\|logs]` | **restart G2's voice service on the Pi** (when he does not answer voice commands; it works even when he cannot hear you). Ends an exploration session first; waits until he is listening again (about 30 s). `status` = what is running and the last thing he heard; `logs` = the voice service log. Prints "restarting voice loop..." then "voice loop restarted: G2 is listening", and G2 says "I am online." out loud when he is back. Voice version: say "restart your voice service" (also "reset your voice", "restart voice"); he says "Restarting voice loop" and, when back, "I am online."; it only works while he is hearing you. |
| `ssh $G2_PI 'cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.diag.crashwatch 5'` | **why did the voice service (or an exploration session) crash?** The last 5 unclean ends: the stage G2 was in, memory and temperature at the time, the fault trace, the last log lines |
| `g2floor [label\|status\|epochs]` | **the floor G2 is on, and the automatic run logs.** `g2floor tile` sets the label every automatic run log records (fits are per floor); no argument shows it; `status` lists the runs captured, their size and why they ended; `epochs` lists the hardware epochs. Tell Claude when hardware changes so a new epoch is added. |
| `g2picscurate [IN] [OUT]` | **curate the pulled exploration pictures** (run `g2pics pull` first): scores lighting, contrast and sharpness, sets aside every picture with a person in it (the camera's own detector, an outside person model if `~/g2_data/models/yolox_s.onnx` exists, and any picture you flag with the **Person** button on the `g2pics` page; never copied; no time-window rule, so clean pictures of the place are kept), adds object category hints (green boxes on the contact sheets; hints only), rejects dark / blown / blurry survey pictures, flags weak named ones, removes near-duplicates keeping the best, and writes `keep/`, `rejects/`, a contact sheet per group, `manifest.json` and `summary.txt` to `training_data/exploration/<date_time>`. Input is never modified. |
| `g2cal [build\|status\|show [ID]\|harm-check ID POLICY...\|approve ID\|reject PARAM [NOTE]\|unreject PARAM\|revert\|auto]` | **the real-data calibration builder**: fits what G2's logs support into numbered snapshots, checks them against V2.1 and V3 (idle Mac only) and applies the approval rules. `approve` is how a first snapshot or a change beyond noise goes live. |
| `g2bg [start [MIN]\|stop\|status\|once]` | **the Mac-side background loop** (every 30 min): re-curates the exploration pictures (`g2picscurate`) and runs the calibration step (sync the Pi's run logs, ingest, `g2cal auto`). It ends when the Mac restarts or logs out: `g2bg start` again. (launchd cannot run scripts under ~/Desktop without Full Disk Access for /bin/bash.) `g2calauto status` shows the snapshots and last calibration lines. |
| `g2pimem [facts\|log N\|search q\|usage\|stop]` | G2's **real** memory on the Pi in the same review page (opens on Facts; Conversations, Observations, Pictures and Trash are tabs; an X on every record, Undo, a backup before the first delete). With a subcommand it prints text instead (`facts`, `log 20` = transcript, `search q`, `usage`). `g2mem` reads the Mac's copy. |
| `g2mem usage` / `consolidate [--apply]` / `pin N` / `unpin N` / `sightings [N]` | per-fact use counters, the sleep-time consolidation pass (dry-run without `--apply`), keep a fact in the core block, the sightings log |
| `python -m pi_pipeline.power runtime test start\|collect\|cancel` / `runtime list\|add\|forget\|plugged\|unplugged` | the Pi battery runtime test (start from a FULL charge, then unplug) and its recorded runs |
| `python pi_pipeline/gait/stand_log.py --minutes 20 --log x.csv` | passively log G2 standing (roll/pitch swing, dominant frequency, voltage) to catch a posture wobble; stop `g2-voice` first |
| `python -m pi_pipeline.vision.exposure_sweep --label bright --out /tmp/ae` | measure how the camera's exposure offset changes a scene's brightness (run with the lamp on, then off) |
| `python -m pi_pipeline.memory.webui` | local web UI to browse / prune memory — `http://127.0.0.1:8899` |
| `g2feat [--profiles]` | resolve `G2_FEATURES` / list the staged bring-up profiles |
| `g2traits [spec]` | resolve `G2_TRAITS` → prompt / behaviour / bonds |
| `g2diag [list\|summarize sid\|tail sid\|replay sid]` | read a diagnostics session |
| Command | Does |
|---|---|
| `python -m pi_pipeline --profiles` | list feature-flag bring-up stages |

## 8. Simulation and RL

### Training / the automated loop

| Command | Does |
|---|---|
| `g2train <tag>` | Start a training run (checklist, TensorBoard, background). e.g. `g2train v9` |
| `python train.py --tag <tag> --steps 2000000` | Run directly (from `rl_training/opencat-gym/`, venv active) |
| `python train.py --tag <tag> --from trained/<ckpt>_ppo --steps 1000000` | Finetune from a checkpoint (note: diverged in Run 5 — use fresh) |
| `touch rl_training/opencat-gym/STOP` | Ask the automated loop to stop cleanly after the current iteration |
| `pgrep -fl "train.py"` | Is a training run active? (shows PID) |
| `pkill -f "train.py"` | Stop all training runs |
| `tail -f rl_training/opencat-gym/trained/<tag>_console.log` | Watch a run's live SB3 output |

### Watching a policy (PyBullet GUI — run from your own terminal)

> GUI windows do **not** appear when launched from a background/detached process.
> Run these in an interactive terminal. Every run is a fresh randomised episode
> (not a loop of one recording); close the window to stop.

**`watch.py` — pick a policy + a challenge.** From `rl_training/opencat-gym/`:

| Command | Does |
|---|---|
| `python watch.py --list` | Print every challenge name |
| `python watch.py` | `run20m_ppo`, flat ground, cruise (0.10 m/s) |
| `python watch.py --challenge slope-up` | **Just one challenge** — a 12° climb. Also: `slope-up-gentle` (5°), `slope-up-steep` (15°), `slope-down` (−12°), `slope-down-steep` (−24°), `cross-slope` (5° roll) |
| `python watch.py --challenge obstacles` | 35 mm obstacle field. Also `obstacles-small` (20 mm), `obstacles-big` (50 mm), `obstacles-huge` (85 mm) |
| `python watch.py --challenge shoves` | Repeated 0.55 shoves. Also `one-shove` (single hard hit), `shoves-hard` (1.0 magnitude) |
| `python watch.py --challenge step-down` | 30 mm drop. Also `threshold-up` (15 mm), `step-up` (30 mm), `big-ledge` (45 mm random) |
| `python watch.py --challenge weak-servos` | 60% torque cutback + a −12° descent |
| `python watch.py --challenge slope+obstacles` | 9° slope + 30 mm obstacles |
| `python watch.py --challenge carpet` | **The rough-terrain course** (`run20m_carpet` training substrate): one heightfield, 13 mm multi-octave bumps + a broad ~±11 mm/1.5 m rolling swell, floor never shows. `carpet-rough` = 19 mm bumps + bigger swell. Auto-extends to 2000 steps; `--steps N` to override |
| `python watch.py --challenge rubble` | **Dense tumbled rubble** — hundreds of rounded chunks (spheres / capsule ridges / some angular) half-sunk in the ground so feet deflect over rather than catch an edge, 15 mm exposed-height cap. `rubble-hard` = bigger/denser. *Superseded by `carpet` for training* — kept for viz. Auto-extends to 2000 steps; `--steps N` to override |
| `python watch.py --challenge gauntlet` | **The hard combined test (T5.1):** 4°/9° slope + 40 mm obstacles + repeated shoves |
| `python watch.py --challenge brutal-gauntlet` | **The T6.4 hardened tier:** 20° slope + 70 mm + 1.0 shoves |
| `... --cmd 0.13` | Change the forward-speed command (creep ≈ 0.04, cruise 0.10, fast ≈ 0.14, backward < 0) |
| `... --speed 0.5` | Slow-mo (0.5×); `--speed 2` = 2× |
| `... --dr clean` | Drop the non-challenge DR (no payload). Default `payload` = the deployment config; `full` = training DR |
| `... --model trained/checkpoints/<tag>_<N>_steps` | Watch a mid-training snapshot instead of `run20m_ppo` |
| `python watch.py --challenge <name> --gif` | **If the GUI window won't open** (Intel Python under Rosetta, headless box): render the challenge to `watch_<name>.gif` instead. `--runs 4` for more episodes. `open watch_<name>.gif` |
| `pkill -f watch.py` | Close it (or Ctrl-C / close the window) |

**`g2watch` / `watch_trained.py` — quick "just show me the gait" (loops):**

| Command | Does |
|---|---|
| `g2watch` | GUI replay of the newest `trained/*_ppo.zip`, episode after episode. Shell fn in `~/.bash_profile`. |
| `g2watch trained/<tag>_ppo` | A specific policy — e.g. `g2watch trained/run20m_ppo` |
| `g2watch trained/checkpoints/<tag>_<N>_steps` | A mid-training snapshot |
| `python watch_trained.py trained/<ckpt> --dr-terrain 0.012` / `--dr-push 0.35` | Replay on one held-out disturbance |
| `pkill -f watch_trained.py` | Close it |

### TensorBoard

| Command | Does |
|---|---|
| `open http://localhost:6006/` | Open the dashboard (started automatically by `g2train`) |
| `python -m tensorboard.main --logdir trained/tensorboard_logs/ --port 6006` | Start it manually |
| `pkill -f "tensorboard.*tensorboard_logs"` | Stop it |

Run → `PPO_N` mapping is in the per-run logs (`docs/auto-iteration-log*.md`).

### Evaluating a policy — scored, headless

All from `rl_training/opencat-gym/`, venv active. `<ckpt>` = e.g. `trained/run20m_ppo`.

| Command | Does |
|---|---|
| `python evaluate_policy.py <ckpt> --episodes 8` | Quick metrics: speed, yaw drift, trot corr, stride, startup ratio, foot clearance |
| `... --dr-terrain 0.012` / `--dr-push 0.35` / `--dr-friction 0.3` / `--dr-mass 0.15` / `--dr-gyro 0.02` | Grade on one held-out disturbance (any `--dr-*` zeroes all knobs first) |
| `... --frames-dir eval_frames/<name>` | Also dump ~30 frames for a look |

#### The decathlon — the graded easy→brutal ladder, learned vs scripted

| Command | Does |
|---|---|
| `python benchmark_decathlon.py --learned <ckpt> --episodes 24 --json-out /tmp/dec.json` | Run **all** cells T1–T7 (flat, slopes, obstacles, stumble-catch, gauntlet, T6 hardened, T7 ledge). Prints fell% / speed / cond-survival per cell |
| `python benchmark_decathlon.py --learned <ckpt> --episodes 28 --hw i --scripted-from trained/decathlon_hw1_i_hw.json --json-out <out>.json` | Score the learned gait through G2's **real control path** (5 Hz IMU + `i` command timing); reuses the saved scripted scores (~half the runtime) |
| `... --extra-dr payload` | **Deployment config:** 75 g payload forced on, rough + torque-cutback off (the number that matters for hardware) |
| `... --extra-dr clean` | No payload / rough / cutback — cell tests exactly its label |
| `... --extra-dr full` | Training DR (payload 90%, rough 35%, cutback 40%) |
| `... --scripted-balance 0.5` | Give the scripted `wkF` baseline a gyro-balance assist (fairer comparison) |
| `... --gif-dir /tmp/dec_gifs` | Also render the gauntlet cell, learned + scripted |
| `python build_decathlon_report.py /tmp/dec.json` | Turn the JSON into an HTML report |

> No single-cell flag on the decathlon — for one challenge use `watch.py --challenge <name>`
> (visual) or `evaluate_policy.py --dr-<knob>` (scored, single knob).

#### Other scored benchmarks

| Command | Does |
|---|---|
| `python benchmark_commanded.py --learned <ckpt> --episodes 16 --json-out /tmp/cmd.json` | Speed-command tracking: creep / cruise / fast / backward / stand / turn — commanded vs achieved, heading drift |
| `python benchmark_gaits.py --learned <ckpt> --episodes 28 --scripted-balance 0.5` | Head-to-head vs scripted `wkF` on flat + obstacle courses (distance, trot corr, falls) |
| `python benchmark_recovery.py <ckpt-a> <ckpt-b>` | Bare-robot stance-recovery probe (payload OFF, rough + escalating shoves) — the decathlon can't see recovery with the payload on. Compares two checkpoints |
| `python robustness_sweep.py --learned <ckpt> --seeds 16 --json-out /tmp/rob.json` | Sweep each sim-to-real axis (payload mass, cmd latency, joint offset, IMU noise, torque cutback) one at a time — where does the gait break? |
| `python render_showcase.py --learned <ckpt> --out showcase.gif` | One annotated GIF of every skill back-to-back (cruise / creep / fast / stand / shoves / slopes / gauntlet / thresholds / steps). `--scripted-balance 0.5` for the scripted version |
| `python render_gif.py <ckpt> out.gif --steps 250 --stride 2` | One episode → animated GIF |

### wkF reference gait (imitation reward)

| Command | Does |
|---|---|
| `python reference_gait/build_wkf_reference.py` | Rebuild `wkf_ref.npy` from `InstinctBittleESP.h` |
| `python reference_gait/verify_wkf_reference.py` | Score sign/mirroring variants by open-loop forward walk |
| `python reference_gait/verify_wkf_reference.py identity --render` | Render the open-loop reference playback to a GIF |
| `python reference_gait/build_skill_reference.py rc rl` | Decode any OpenCat skill from `InstinctBittleESP.h` → `<name>_ref.npy` |
| `python reference_gait/verify_getup_reference.py --gif --sheet` | Replay the firmware `rc`/`rl` get-up in PyBullet (H9). 0/2 recover — see `docs/rl/getup-sim-replay.md` |

### RL training — detail

#### Common rules for `rl_training/opencat-gym/`

- **Run from that directory** (scripts import `opencat_gym_env` locally, load `models/` by relative path).
- **Use the RL venv**: `source .venv/bin/activate` from the repo root, or call `../../.venv/bin/python`.
- **Every run needs a unique `<tag>`** — it names `trained/<tag>_ppo.zip`, `trained/checkpoints/<tag>_<steps>_steps.zip`, `trained/<tag>_console.log`. Reusing a tag overwrites. Convention: `v6`, `v7`, ….

#### Start a run by hand (when `g2train` isn't available)

```bash
cd rl_training/opencat-gym
ls trained/ | grep <tag>                         # 1. tag unused? expect no output
pgrep -fl train.py                               # 2. no run active
pkill -f "watch_trained.py|view_sim.py"          # 3. close sim viewers (they steal CPU)
../../.venv/bin/python smoke_train.py            # 4. if you edited the env/train.py (~90s, reward in-range, no nan)
pgrep -f "tensorboard.*tensorboard_logs" || nohup ../../.venv/bin/tensorboard   --logdir trained/tensorboard_logs/ --port 6006 > trained/tensorboard.log 2>&1 &   # 5.
nohup ../../.venv/bin/python train.py --tag <tag> > trained/<tag>_console.log 2>&1 &  # 6. launch
echo "PID $!"                                    #    write this down
tail -n 20 trained/<tag>_console.log             # 7. verify: "Logging to ...PPO_N", ep_rew_mean a real number, fps in the hundreds
```
When it finishes: `g2watch`, then record the result in the matching log under `docs/rl/`.

#### `start_run.sh` flags (from `rl_training/opencat-gym/`)

| Command | Effect |
|---|---|
| `./start_run.sh v8` | normal run |
| `./start_run.sh v8 --steps 20000` | short run — extra args pass to `train.py` |
| `./start_run.sh v8 --force` | allow a tag whose files already exist (overwrites) |

#### Continue a run (reward function UNCHANGED)

```bash
cd rl_training/opencat-gym
# edit continue_train.py first — source checkpoint + output name are hardcoded near the top, NO cli args
pgrep -fl train.py                               # no run active
nohup ../../.venv/bin/python continue_train.py > trained/<name>_console.log 2>&1 &
```
2M more steps with `reset_num_timesteps=False`. Reward change -> fresh `g2train` instead.

#### RL "tests" (no pytest on the RL side)

| Command (from `rl_training/opencat-gym/`) | Verifies |
|---|---|
| `../../.venv/bin/python smoke_train.py` | whole pipeline at 20K steps (~90s): env, PPO loop, logging, checkpoint |
| `../../.venv/bin/python -c "from stable_baselines3.common.env_checker import check_env; from opencat_gym_env import OpenCatGymEnv; check_env(OpenCatGymEnv()); print('OK')"` | env spaces / shapes / return types |

#### One-time env setup

```bash
# RL venv (repo root) — Homebrew python@3.11; macOS system Python too old
python3.11 -m venv .venv && source .venv/bin/activate
CPPFLAGS="-Dfdopen=fdopen" pip install -r requirements.txt   # CPPFLAGS mandatory on macOS (pybullet zlib build bug)
# companion pipeline venv
python3.11 -m venv pi_pipeline/.venv && pi_pipeline/.venv/bin/pip install -r pi_pipeline/requirements.txt
```

## 9. Quick checks and git

### Git landmarks

| Command | Does |
|---|---|
| `git checkout gait-v6-known-good -- rl_training/opencat-gym/opencat_gym_env.py` | Restore the pre-loop v6 reward function |
| `git checkout phase3-gait -- rl_training/opencat-gym/opencat_gym_env.py` | Restore the locked Phase 3 gait config |
| `g2watch trained/phase3-gait_ppo` | Replay the locked Phase 3 gait |
| `git for-each-ref refs/backup/` | Pre-history-rewrite backup refs |

### Quick checks

| Command | Does |
|---|---|
| `ps aux \| grep -iE "python\|pybullet\|tensorboard" \| grep -v grep` | Everything RL-related that's running |
| `../../.venv/bin/python smoke_train.py` | ~90 s pipeline sanity check (reward ~40–60, no NaN) |

## Heading hold and per-foot tests (Pi walks)

| Command | What it does |
|---|---|
| `bash tools/g2_baseline.sh start 4 NAME --foot-hold fl --hold-on-policy --seconds 25 --lead-s 5 --reset-s 5` | 4 logged V2.1 walks of 25 s (about 10 ft) with the front-left hold on |
| `bash tools/g2_baseline.sh start 9 feet --scripted-mix scripted --foot-trim none,fl=-0.25,fl=+0.25,fr=-0.25,fr=+0.25 --lead-s 5 --reset-s 5` | per-foot fixed-trim test on the scripted walk (several feet at once: `fl=-0.3/fr=+0.3`) |
| `G2_FOOT_HOLD=off` in the Pi `.env` | everyday walks without the heading hold (default: on, front-left) |
| `python pi_pipeline/gait/run_gait.py --foot-hold off` | one walk with the hold off (the hold is on by default) |

## Naming pictures by hand (g2pics page)

| Command | What it does |
|---|---|
| `g2pics` | the Pictures tab of the review page; each picture has a **Name** button (type what it is: it moves into that object's folder in the library; Undo in the toast) and a **Person** flag |
| `g2pics stop` then `g2pics` | restart the page after an update |
| Facts tab: **Add fact**, **Edit**, importance 1-5, **Core** | write or change what G2 remembers (a database copy is made before the first change of a session; Undo in the toast) |
| Tag chips (the detector's labels under a picture or on an observation) have an **×** to remove a wrong tag; **Person** can be clicked off again; every removal has an Undo in the toast |
| Observations tab: **Add observation**, **Edit** | write or change what G2 saw (caption and detector labels) |

## Exploration and hold, as of 2026-10-07

| Command | What it does |
|---|---|
| `bash tools/g2_explore.sh start [ROAM_S]` | exploration session (roams by default, 600 s); say "cancel exploration" / "end exploration mode" to end it; it says "Exploration completed." and lies down |
| `bash tools/g2_baseline.sh start N NAME --foot-hold fl --hold-on-policy --seconds 18 --lead-s 5 --reset-s 35` | N logged V2.1 walks with the front-left hold (35 s between walks to tape the offset); `--hold-off` for a no-hold control, `--foot-hold-ff 0,-0.25` for the feed-forward A/B |
| `touch rl_training/opencat-gym/trained/v3_hold_20m` | veto the 20M auto-go (the runner then waits for `trained/v3_go_hardware_checkin`) |
| `bash tools/g2_promote_policy.sh TAG NAME [--dry-run]` | promote a trained policy to the default and deploy it when the Pi is online |
| `touch rl_training/opencat-gym/trained/v3_world2` | training world 2 (payload 6 mm forward) for trainings started afterwards |

## Watching a V3 training run (Mac)

| Command | What it does |
|---|---|
| `tail -f rl_training/opencat-gym/trained/phase_v3.log` | the queue: starts, results, gait checks, stops |
| `tail -f rl_training/opencat-gym/trained/v3_20m_console.log` | the training run's own log (steps, rewards, curriculum levels); TensorBoard logging is off in this repo |
| `ls rl_training/opencat-gym/trained/checkpoints \| grep v3_20m_ \| sort -t_ -k3 -n \| tail -1` | the newest checkpoint (saved every 200k steps) |
| `g2watchrun [--realtime]` | watch the training run going on right now: the actual episodes it is simulating, streamed from the run (no simulation of its own; runs started after 2026-10-09); default follows live at training speed, `--realtime` plays each episode at real speed; works from any directory |
| `g2watchsim [TAG] [--dr-push 0.35]` | (the old `g2watchrun`) a fresh simulation of a run's newest checkpoint in the PyBullet GUI, in the G2 hardware world; `g2watchsim list` shows every run's newest checkpoint. Underneath: |
| `cd rl_training/opencat-gym && ./watch_v3.sh [TAG] [--dr-push 0.35]` | replay the newest checkpoint of a run in the PyBullet GUI, in the G2 hardware world; run it in your own terminal; it slows the training a little while open |
| `python rl_training/opencat-gym/phase_v3.py status` | every finished job and its verdict |
| `g2clean` | list scratch files on the Mac and the Pi that are safe to delete and untracked files that need a commit-or-delete decision (dry run); `g2clean --apply` deletes the scratch list and the Pi's stray files |
