# Operating G2: lessons and standing practice

Things that bit during the hardware sessions of 2026-10-07 to 2026-10-10 and the practice that came out of each. Current state of the robot: [`../STATUS.md`](../STATUS.md). Switches: [`settings-switches.md`](settings-switches.md). Commands: [`cheatsheet.md`](cheatsheet.md).

## Deploying and stopping

- Never deploy to the Pi (or restart `g2-voice`) while an exploration session, a walk or the user's test is running. The deploy script refuses during an exploration or walk. Check with `bash tools/g2_explore.sh status`; a dry run (`rsync -an --itemize-changes ... pi_pipeline/ $G2_PI:bittleX/pi_pipeline/`) shows whether the Pi matches the repo.
- Rest or stand G2 before stopping anything that controls him: `bash tools/g2_safe_stop.sh voice|explore`, never a plain service stop mid-stride.
- If G2 is moving with no process in control, send rest at once: `python -m pi_pipeline.link.check_serial send d` on the Pi.
- After a fall the session halts and `EmergencyStop` re-sends rest; ending the session (`bash tools/g2_explore.sh stop`) stops the twitching. Never wait inside `SerialLink.send` (it is shared and the walk loop starves).
- `tools/g2_deploy_when_online.sh --max-hours 24` waits for the Pi and deploys once; `--once` deploys now; `--cancel` disarms it.

## Voice service and microphone

- **One microphone stream for the life of the process, never closed** (`voice/wake_word.py`). Closing the handed-over `sounddevice` stream crashed PortAudio; opening a second stream fails with "Device unavailable". Follow-up listening windows use the same stream.
- **The microphone is very quiet** (speech at 10 cm is about 20-55 RMS with an offset near −900). The Google voiceHAT card has no mixer controls, so `voice/mic_gain.py` removes the offset and applies ×20 gain (`G2_MIC_GAIN`). Measure with `python -m pi_pipeline.voice.check_audio mic 15` (stop `g2-voice` first).
- **G2 must not hear himself:** the wake detector and command window ignore audio while `tts.SPEAKING` is set and for 0.8 s after.
- Every `P` (Pi battery read) or `gb` (stand guard) makes the BiBoard tick, so the battery is read on demand (start, before a walk) plus a 30 min backstop (`G2_BATTERY_POLL_S`), and stand is re-asserted every 10 min (`G2_STAND_REASSERT_S`). Rapid ticking during runner-started walks is unexplained and parked. Every command that makes the board sound is logged to `~/.local/share/g2/noise.jsonl` (`python -m pi_pipeline.link.noise_log [N]`).
- The systemd unit restarts 1 s after a failure (10 times in 60 s) with faulthandler on. Crash reports: `python -m pi_pipeline.diag.crashwatch` ([`../hardware/diagnostics.md`](../hardware/diagnostics.md)).
- Alarm thresholds live in the Pi `.env`: G2 pack low at 7.75 V (about 35% left), critical 7.4 V; the Pi battery warns at 65% of its measured runtime (`G2_PI_WARN_FRACTION`).
- The name is spoken as "gee two": Piper reads "G2" with a soft g, and a hard-g spelling was misheard by the recognizer as "the to".
- A battery question once crashed the voice loop (a module name clash, fixed). Check that the firmware IMU line still parses when the BiBoard has been on for hours (the yaw field overflowed once and made every IMU line unparseable).
- Sound levels: a sound's `peak` is a fraction of full scale (0.0225); passing a large number clips at full volume. Speaker sounds play only on the Pi (`G2_SPEAKER_SOUNDS`); tests set it to 0.

## Hardware session practice

- Ask which floor G2 is on and set it first (`g2floor <label>`); the label has a 72 h age limit in the ingest gates.
- All tests start on his feet with hands near; the user says "go" before each run and measures with a tape in inches. Abort a block if the G2 pack passes 30% (resting) or the Pi's low alarm sounds (the Pi lasts about 3.3 h on a full charge: low alarm at 2.29 h, critical 2.62 h; record in `~/.local/share/g2/pi_runtime.json`, `python -m pi_pipeline.power runtime list`).
- Capture walks for system identification need `--foot-hold off`, since the front-left hold changes the legs' motion ([`../rl/sysid-capture-plan.md`](../rl/sysid-capture-plan.md)). Stall and collision runs are labelled `collision` and excluded so they never feed a calibration fit.
- A decision rule that worked for new sensing: build a detector only if its runs separate from normal runs by a margin that holds on every repeat (the IMU contact signal separated on heading jitter, 10-13 against 1.4-1.6 deg per update).

### Processing the data after a session

Not automatic: the Pi's autolog skips any walk started with `--log`, and the Mac side runs only when called. In order:
1. Pull every explicit log (`~/g2_runs/*.csv`, rest and stand captures, wall pictures, `wall_dryrun.jsonl`, exploration pictures) to the Mac.
2. `g2data all` for the automatic runs (sync then ingest).
3. `tools/walk_log_summary.py` for the comparisons.
4. Update [`../STATUS.md`](../STATUS.md) and the plan, commit with explicit paths, run `python tools/g2_cleanup.py`.

### Background jobs on the Mac

`g2bg` (`tools/g2_bg_jobs.sh`; `g2bg status|stop|start`, logs in `~/g2_logs/`) runs every 30 minutes: re-curate pictures pulled from the Pi (`tools/g2_curate_auto.sh`), then sync the Pi's run logs, ingest and run the calibration step (`tools/g2_cal_auto.sh`). It skips quietly while the Pi is off, ends at a Mac restart, and runs a snapshot's harm check only when the Mac is idle. launchd cannot run scripts under `~/Desktop` (macOS "Operation not permitted"), hence the plain loop. Calibration approval is automatic by statistical gates ([`../rl/real-data-pipeline.md`](../rl/real-data-pipeline.md)); `g2cal revert` undoes it.

## Design decisions to keep (2026-10-10)

- No camera roll correction (a fixed correction could throw other readings off); left and right turning may be a little off at first.
- Sleep mode is on by default (5 min). The follow-up window is 5 s (8 s after a question). Live with both, then tune.
- Measurements are shown in inches and the battery as a percent.
- Later, once wall avoidance is reliable on several wall types and the planned training photos exist: most random turns off, bounce around like a robot vacuum ([`../vision/wall-check-plan.md`](../vision/wall-check-plan.md)).

## Working in this repo

- macOS: `sed -i` differs (use Python edits), there is no `timeout`, and chained sleeps are blocked (use Monitor until-loops). A command chain with `;` does not stop on a failing test: use `&&` before committing.
- A failing pytest assertion once printed an API key (a `Settings` repr); tests compare plain numbers now. Filter full-suite output for `sk-ant` before pasting it anywhere.
- The privacy hook flags the user's first name in docs and docstrings.
- Training-run pitfalls: [`../rl/training-upgrade-2026-10.md`](../rl/training-upgrade-2026-10.md) section 7.
