# Operating notes: constraints and practice

This page lists the operating constraints and standing practice that follow from how G2's hardware and services behave. Current state: [Status](../STATUS.md). Switches: [Settings and switches](settings-switches.md). Commands: [Cheat sheet](cheatsheet.md). Safety rules: [Operating G2](operating-g2.md).

## Deploying and stopping

- Deploy only when idle: New code is not deployed to the Pi, and `g2-voice` is not restarted, during an exploration, a walk or a test. The deploy script refuses during an exploration or a walk. `bash tools/g2_explore.sh status` shows the state, and a dry run (`rsync -an --itemize-changes ... pi_pipeline/ $G2_PI:bittleX/pi_pipeline/`) shows whether the Pi matches the repository.
- Stop controlling services safely: `bash tools/g2_safe_stop.sh voice|explore` rests or stands G2 first. A plain service stop mid-stride is not supported.
- Moving with no process in control: `python -m pi_pipeline.link.check_serial send d` on the Pi sends rest at once.
- After a fall: The session halts and `EmergencyStop` re-sends rest. Ending the session (`bash tools/g2_explore.sh stop`) stops any twitching. `SerialLink.send` never waits, because the link is shared and a wait starves the walk loop.
- Deploying when the Pi comes online: `tools/g2_deploy_when_online.sh --max-hours 24` waits for the Pi and deploys once, `--once` deploys now, and `--cancel` disarms the wait.

## Voice service and microphone

- One microphone stream for the life of the process. The stream is never closed (`voice/wake_word.py`). Closing the handed-over `sounddevice` stream crashes PortAudio, and opening a second stream fails with "Device unavailable". Follow-up listening windows use the same stream.
- Microphone level: Speech at 10 cm measures about 20 to 55 RMS with an offset near −900. The Google voiceHAT card has no mixer controls, so `voice/mic_gain.py` removes the offset and applies ×20 gain (`G2_MIC_GAIN`). `python -m pi_pipeline.voice.check_audio mic 15` measures it, with `g2-voice` stopped first.
- Self-hearing: The wake detector and the command window ignore audio while `tts.SPEAKING` is set and for 0.8 s afterwards, so G2 does not hear himself.
- Board ticks: Every `P` (Pi battery read) or `gb` (stand guard) makes the BiBoard tick. The battery is therefore read on demand (at start and before a walk) with a 30 minute backstop (`G2_BATTERY_POLL_S`), and the stand state is re-asserted every 10 minutes (`G2_STAND_REASSERT_S`). Rapid ticking during runner-started walks is unexplained. Every command that makes the board sound is logged to `~/.local/share/g2/noise.jsonl` (`python -m pi_pipeline.link.noise_log [N]`).
- Restart policy: The systemd unit restarts the service 1 s after a failure (up to 10 times in 60 s) with faulthandler enabled. `python -m pi_pipeline.diag.crashwatch` reports crashes ([Diagnostics](../hardware/diagnostics.md)).
- Alarm thresholds: They live in the Pi `.env`. G2's pack warns at 7.75 V (about 35% left) and is critical at 7.4 V. The Pi battery warns at 65% of its measured runtime (`G2_PI_WARN_FRACTION`).
- Spoken name: The name is spoken as "gee two". Piper reads "G2" with a soft g, and a hard-g spelling is misheard by the recognizer.
- IMU line health: The firmware IMU line must still parse after the BiBoard has been on for hours. An overflowing yaw field makes every IMU line unparseable.
- Sound levels: A sound's `peak` is a fraction of full scale (0.0225), so a large value clips at full volume. Speaker sounds play only on the Pi (`G2_SPEAKER_SOUNDS`), and tests set it to 0.

## Hardware session practice

- Floor label: The floor G2 stands on is set first (`g2floor <label>`). The ingest gates accept a label up to 72 h old.
- Test start: Every test starts with G2 on his feet and a hand within reach. Each run starts on an explicit go, and distances are measured with a tape in inches.
- Abort criteria: A block of testing ends when G2's pack passes 30% at rest or the Pi's low alarm sounds. The Pi lasts about 3.3 h on a full charge, with the low alarm at 2.29 h and critical at 2.62 h. The runtime record is `~/.local/share/g2/pi_runtime.json` (`python -m pi_pipeline.power runtime list`).
- System-identification captures: They run with `--foot-hold off`, because the front-left hold changes the legs' motion. Stall and collision runs are labelled `collision` and excluded, so they never feed a calibration fit.
- Adding a detector: A new detector is built only if its runs separate from normal runs by a margin that holds on every repeat. The IMU contact signal qualified: heading jitter was 10 to 13 deg per update against 1.4 to 1.6 for normal walking.

### Processing the data after a session

Processing is not automatic. The Pi's autolog skips any walk started with `--log`, and the Mac side runs only when called. In order:
1. Pull every explicit log (`~/g2_runs/*.csv`, rest and stand captures, wall pictures, `wall_dryrun.jsonl`, exploration pictures) to the Mac.
2. Run `g2data all` for the automatic runs (sync, then ingest).
3. Run `tools/walk_log_summary.py` for the comparisons.
4. Update [Status](../STATUS.md), commit with explicit paths, and run `python tools/g2_cleanup.py`.

### Background jobs on the Mac

`g2bg` (`tools/g2_bg_jobs.sh`, with `g2bg status|stop|start`, logs in `~/g2_logs/`) runs `tools/g2_sync.sh` (`g2sync`) every 30 minutes. It copies everything from the Pi to the Mac, each item on its own schedule:
- Goal data and **exploration pictures**, with curation by `tools/g2_curate_auto.sh`.
- Run logs, with ingest and the calibration step (`tools/g2_cal_auto.sh`).
- Wall pictures, every 30 minutes.
- A memory database snapshot and **the logs**, once a day.

`g2sync status` shows when each copy last worked and flags a stale one. The review page shows the same line under its title and has a **Sync from the Pi** button. The job skips quietly while the Pi is off or busy (an exploration, a goal session, a walk or a hardware test), ends at a Mac restart, and runs a snapshot's harm check only when the Mac is idle. launchd cannot run scripts under `~/Desktop` (macOS reports "Operation not permitted"), so a plain loop runs the job.

Calibration approval is automatic through statistical gates ([Real-data pipeline](../rl/real-data-pipeline.md)), and `g2cal revert` undoes it.

## Defaults

- Camera roll: No camera roll correction is applied, because a fixed correction could throw other readings off. Left and right turning can be slightly off until the pace is measured.
- Sleep: Sleep mode is on by default, after 5 minutes at rest. The mic stays open 3 s after a reply (`G2_FOLLOW_UP_S`) and 3 s after a question (`G2_QUESTION_WINDOW_S`).
- Units: Measurements are shown in inches and the battery as a percent.
- Random turns. Most random turns are meant to be switched off, with G2 bouncing around like a robot vacuum, once wall avoidance is reliable on several wall types (Wall check plan).

## Working in the repository

- A command chain that must stop on a failing test uses `&&` before committing, because `;` continues past a failure.
- A failing pytest assertion can print a settings object. Tests compare plain numbers, and full-suite output is filtered for `sk-ant` before it is shared.
- The privacy hook flags personal names in docs and docstrings, so tracked files use placeholders.
- Committing is local. `git push origin development` is a deliberate step, because the repository is public.
- Capture folders, `trained/` files and the memory database are looked at before deleting, because they are not all reproducible.
