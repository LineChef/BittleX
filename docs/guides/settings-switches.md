# Settings and switches (environment variables)

Set in the Pi's `.env` (never `cat` that file; add a line with `echo 'KEY=value' >> .env`, restart the service) or in the environment of a one-off command. Defaults are what the code does with no setting.

## Sounds

| Switch | Default | What it does |
|---|---|---|
| `G2_SPEAKER_SOUNDS` | on for the Pi, off on a dev machine | `1` plays speaker sounds on any machine (audition only; the volume is a tiny fraction of full scale) |
| `G2_REFUSE_SOUND` | on | the losing horn when he refuses a request (a gait he cannot switch to) |
| `G2_FAIL_SOUND` | on | the losing horn when a command fails (once per 8 s) |
| `G2_FALL_HORN` | on | the losing horn when he tips over (tilt past 60 degrees for 0.3 s), walking or not |
| `G2_GRUNT` | on | the grunt when you rebuff him |
| `G2_COMPLETE_SOUND` | on | the ta-da at the end of an exploration |
| `G2_WALL_SOUND` | on | the two-note turn-away sound |
| `G2_HIT_SOUND` | on | the long "ooooof" when he hits a wall |
| `G2_ACK_TONE` | `short_tone` | what acknowledges a command sent to Claude: `short_tone`, `ack_whistle`, `buzzer`, `off` (`star_trek_whistle` still works) |
| `G2_FOLLOW_UP_S` | 5 | seconds the mic stays open after a reply (0 = no window, so no closing notes); `G2_QUESTION_WINDOW_S` (8) after a question |

## Exploration and walls

| Switch | Default | What it does |
|---|---|---|
| `G2_EXPLORE_ROAM_S` | 600 | the roam time of a voice-started exploration |
| `G2_EXPLORE_HANDOVER` | on | `0` stops "explore" from handing over to an exploration session |
| `G2_WALL_STEER` | on | `0` turns off wall steering (and the 3 s looks) |
| `G2_HIT_WALL` | on | `0` turns off the hit-a-wall sequence |
| `G2_WALL_DRYRUN` | on | `0` turns off the wall estimator and its log entirely |
| `G2_PLACE_LOG` | on | `0` stops the place-memory record of survey stops (`place_stops.jsonl` beside the exploration pictures) |
| `G2_REFLECT` | `dry` | Reflection on his own experience (one Claude call per new exploration session): `off`; `dry` logs the notes it WOULD save to `~/.local/share/g2/reflections_dry.jsonl`; `on` saves them as facts (source "experience") |
| `G2_EXPERIENCES` | `~/.local/share/g2/experiences.jsonl` | Where the per-session exploration recaps are kept (on the Pi) |
| `G2_MEMORY_CALL_LOG` | `~/.local/share/g2/memory_calls.jsonl` | The record of every memory-processing call (tidy-up and reflection): `python -m pi_pipeline.memory calls [--days N]` |
| `XIAOZHI_MCP_ENDPOINT` | unset | The AI head agent's secret MCP access-point address (`wss://…`), from the xiaozhi.me console. Only in the Pi's `.env`, never in chat, logs or the repo. `python -m pi_pipeline.head` connects to it and offers the head's model a few harmless tools |
| `G2_WALL_LOOK_SLOW_S` | 6 | the look interval when no wall was seen within 40 in in the last 20 s (3 s otherwise) |
| `G2_INTEREST_EVERY_S` | 3 with steering, else 10 | the look interval (overrides the above) |
| `G2_PICTURE_PREP_EVERY_S` | 0 | camera warm-up for every picture (0) or only every N seconds |
| `G2_SURVEY_COOLDOWN_S`, `G2_SURVEY_FIRST_S` | 60, 30 | at most one picture stop this often; the first after this long |
| `G2_WALL_CAL`, `G2_WALL_LOG`, `G2_WALL_PICS` | under `~/.local/share/g2/` | calibration file, look log, ring of near-wall pictures |
| `G2_WALL_PICS_DIR` | `~/g2_wall_pics` | where `wall_pictures` saves the recognition shots |

## Power and battery

| Switch | Default | What it does |
|---|---|---|
| `G2_SLEEP_AFTER_S` | 300 | seconds at rest before power-saving sleep (0 = off); the wake word wakes him with a yawn |
| `G2_BATTERY_LOW_V`, `G2_BATTERY_CRITICAL_V` | 7.54, 7.46 | G2 pack alarms at rest (about 30% and 20%); `G2_BATTERY_LOAD_LOW_V` 7.3 and `G2_BATTERY_LOAD_CRITICAL_V` 7.2 under load |
| `G2_PI_WARN_FRACTION`, `G2_PI_CRITICAL_FRACTION` | 0.70, 0.80 | Pi battery alarms as a share of the measured runtime (3.28 h); critical backs off to every 15 min |
| `G2_POWER_LOG` | `~/.local/share/g2/power_log.jsonl` | the power diary |

## Walking and standing

| Switch | Default | What it does |
|---|---|---|
| `G2_STAND_RAMP_S` | 0.8 | the eased stand-up (`off` / 0 = the old single jump; tests turn it off) |
| `G2_TRANSITION_RAMP_S` | 2.0 | the longest eased move into a firmware skill's first frame (`link/transitions.py`); a move takes as long as its fastest joint needs to stay under 80 deg/s (110 into the bow, 100 into the sit, 120 into the check; at least 0.25 s), sent 40 times a second; `off` / 0 = the firmware's own jump; tests turn it off |
| `G2_WAKE_LOG` | `~/.local/share/g2/wake_triggers.jsonl` | every wake trigger and what followed it, for counting false triggers (`python -m pi_pipeline.voice.wake_log --days 7`); `off` turns it off |
| `G2_WAKE_MIN_CONF` | 0 | a wake phrase Kaldi is less sure of than this (0 to 1, lowest word confidence) is ignored; 0 = off. Every trigger logs its confidence (`journalctl -u g2-voice \| grep "wake word"`); pick the value once real calls and background talk separate |
| `G2_EXPLORE_INPROCESS` | 0 | `1`: "go ahead and look around" runs the exploration inside the voice service (same link, walker, memory, speech engine and microphone; no stop and restart of `g2-voice`, no second Piper/Vosk load). Needs `explore`, `vision` and `vision_safety` on in the service's own `G2_FEATURES`; otherwise, or at `0`, the separate `g2-explore` session runs as before. Not yet tried on G2 |
| `G2_FLOOR_TRIM_MAX_AGE_H` | 12 | a floor label older than this is not used to pick a per-floor trim (`g2attach floor-trim`); the general trim applies |
| `G2_BODY_STATE` | `~/.local/share/g2/body_state.json` | how the body has been doing (low battery, a recent fall, the last exploration), folded into each Claude turn's mood hint and the idle timing (`personality/body.py`); `off` turns it off |
| `G2_FLOOR_PROMPT_S` | `10` | how long G2 listens for the answer when he asks "Which floor am I on?" before a voice-armed roam (0 turns the question off). Asked when the floor label is unknown or older than `G2_FLOOR_PROMPT_MAX_AGE_H` (default `1` hour); answer a floor ("tile") or "same"; no answer never blocks the roam |
| `G2_FLOOR_MAX_AGE_H` / `G2_FLOOR_SKIP` | `1` / `0` | `tools/g2_explore.sh start` and `stationary` ask for the floor on a terminal when the label is unknown or older than this many hours; with no terminal the start is refused (set it with `g2floor tile`) unless `G2_FLOOR_SKIP=1` |
| `G2_WAKE_MAX_BEFORE` | unset (off) | a wake phrase with more than this many other words before it in the same utterance is ignored (talk nearby, not a call); `wake_log` prints the words-before counts for real and false triggers and a suggested `G2_WAKE_MIN_CONF` |
| `G2_MIC_WATCHDOG` | 1 | a supervised keeper reopens the microphone stream when no audio block has arrived for 6 s (backlog B27); `0` = off |
| `G2_SPEECH_CACHE` | `~/.cache/g2/speech` | disk cache of synthesised speech lines, so a line said before costs no synthesis (the exploration speech lag); `off` turns it off |
| `G2_SPEECH_PREWARM` | 1 | a minute after the voice service starts, make the fixed exploration narration lines into the cache at low priority; `0` = off |
| `G2_SURVEY_AFTER_WALL` | 1 | a finished wall turn-away is also a place for a survey picture (same cooldown); `0` = surveys only at the end of a clean leg |
| `G2_SURVEY_EXTRA_FRAMES` | 2 | a survey picture takes this many more frames half a second apart and keeps the sharpest (local edge measure); `0` = one frame |
| `G2_SURVEY_RELAX_S` | 60 | after this many seconds with no survey picture the "far from a wall" and "something interesting" requirements are lifted; `0` = never |
| `VISION_SENSOR_OPT` | 1 (0 in exploration) | the camera's capture option for detection (0 = 240, 1 = 480); exploration sessions use 0, the picture option, so a picture needs no capture-mode switch |
| `G2_PROFILE` | 0 | `1` runs a sampling profiler during an exploration session (`diag/sampler.py`): which threads use the CPU and where; the report is `profile.txt` in the session's diagnostics folder |
| `G2_TRANSITION_READ_POSE` | off | stage 2 of the eased transitions: after a firmware gait or a trick (pose unknown) the link reads the servos (`f`, two agreeing rows) and eases from the measured pose; off until `python -m pi_pipeline.link.check_serial posecheck` passes on G2 |
| `G2_WALK_RAMP_S` | 0 | opt-in speed ramp-in at the start of a policy walk, in seconds (the sim check showed no gain) |
| `G2_FOOT_TRIM` | policy default | `off` disables the foot trim (V6 default `fl=-0.3`) |
| `G2_ANNOUNCE_ONLINE` | on | `off` silences "G2 online." |

## Exploration pictures, contact and one-sound-at-a-time (2026-10-10)

| Switch | Default | What it does |
|---|---|---|
| `G2_SURVEY_CHECK` | on | a survey stop is look up, look down, stand, firmware `check` (`kck`, the body lean; G2 has no head to pan), stand, settle, one picture; `0` skips the check |
| `G2_SURVEY_LOOKS` | off | `1` adds left and right turns with a throwaway picture each (open-loop turns were off by 30 to 70 deg) |
| `G2_NEAR_LOOK_IN` | 30 | a wall this close (inches) starts the fast 3 s wall looks and blocks surveys and object checks for 20 s |
| `G2_SURVEY_FIRST_S`, `G2_SURVEY_COOLDOWN_S`, `G2_INTEREST_FALLBACK_S` | 30, 60, 300 | survey pacing; the fallback is a random 0.6 to 1.4 times this |
| `G2_WALL_KEEP_ALL` | off | `1` keeps a picture of every wall look (a hit test); `tools/g2_explore.sh` passes it through |
| `G2_IMU_CONTACT` | on | the walk loop's heading-jitter signal (6 deg per IMU update over 3 s, 8 samples) starts the hit sequence (oof, back up, turn) even when vision says clear |
| `G2_CONTACT_PICS`, `G2_CONTACT_PICS_DIR` | on, `~/.local/share/g2/contact_pictures` | two instant frames at a stall or hit, for diagnosis only |
| `G2_STALL_LOG` | on | log-only 8 s stall detector (`imu.stall_suspect`) |
| `G2_AUDIO_GATE` | on | speech, sound effects and BiBoard beeps wait for each other (up to 4 s, then a safety sound cuts in) |
| `G2_NARRATE_START_QUIET_S` | 8 | no narration for the first seconds of an exploration |
| `G2_WALL_STEER` | on | `0` turns the wall turn-away off (used to let him walk into a wall and test the hit sequence) |

## Locations, logs and limits (added 2026-10-17)

Where G2 keeps things, and the limits people occasionally change. Every variable the code reads, with its default, is listed in [`env-reference.md`](env-reference.md).

| Switch | Default | What it does |
|---|---|---|
| `G2_API_LOG` | `~/.local/share/g2/api_calls.jsonl` | the log of every Claude API call (one JSON line each); `off` turns it off. Read with `g2api` |
| `G2_API_PRICE` | `3,15` | input and output dollars per million tokens, used for the cost estimate; set it to match the current price list |
| `G2_USAGE_FILE` | `~/.local/share/g2/api_usage.json` | per-day call and token counts, including retries (`python -m pi_pipeline.voice.usage`) |
| `G2_BATTERY_WATCH` | on | the low-battery watch for G2's pack; `0` turns it off |
| `G2_BATTERY_LOG`, `G2_BATTERY_LOG_EVERY_S` | `~/.local/share/g2/battery_voltage.csv`, 300 | the pack-voltage history, one line per interval (an empty path turns it off) |
| `G2_PI_RUNTIME_LOG` | `~/.local/share/g2/pi_runtime.json` | the measured Pi battery runs |
| `G2_AUTOLOG_DIR` | `~/g2_runs/auto` | where the automatic walk logs go |
| `G2_RUNS_DIR`, `G2_LOG_DIR` | `~/g2_runs`, `~/g2_logs` | walk logs and diagnostics sessions; both are tidied after `G2_TIDY_DAYS` |
| `G2_CAP_DIR` | `~/g2_cap` | the camera preview's captures, cleared at every voice-service start (pull them first with `g2pcam-pull`) |
| `G2_DETECTION_LOG_DIR` | `~/g2_runs/detections` | the detection log folder |
| `G2_EXPLORE_PICTURES_DIR` | `~/.local/share/g2/explore_pictures` | the exploration pictures |
| `G2_NOISE_LOG` | `~/.local/share/g2/noise.jsonl` | the log of BiBoard commands that make a noise; `off` turns the file off |
| `G2_GAIT_MODE_FILE`, `G2_GALLERY_PENDING` | `~/.local/share/g2/gait_mode.json`, `.../gallery_pending.json` | the shared gait mode and the pictures queued for the object gallery |
| `G2_STATE_DIR` | `~/.local/share/g2` | where `bringup` keeps its progress file |
| `G2_DEFAULT_GAIT` | `policy` | `firmware` goes back to the stock scripted `wkF` for forward walking |
| `G2_CONVERSATION_WINDOW_S`, `G2_CONVERSATION_MAX_S` | 20, 600 | conversation mode ("let's talk"): how long G2 waits for you to start each turn, and the session limit; 0 for the window turns the mode off |
| `G2_CONVERSATION_MAX_WORDS`, `G2_SIDE_MAX_WORDS` | 30, 14 | a turn heard without the wake word that runs longer than this is dropped before Claude (the first number applies in conversation mode); 0 means no limit |
| `G2_SIREN_PEAK` | the siren level | loudness of the Pi battery alert siren (a fraction of full scale) |
| `G2_MEMORY_LOG_COMMANDS` | off | `1` logs the memory-related spoken commands |
| `G2_NARRATE_HIDE_NAMES` | off | `1` makes G2 say "someone" instead of the names he knows when narrating |
| `G2_INTEREST` | on | `0` turns off the interest watch that decides when an exploration stop is worth a picture |
| `G2_WALL_LOOK_FAST_S` | 3 | seconds between wall looks while a wall is near |
| `G2_OBJECT_GALLERY_MAX_ENTRIES`, `G2_OBJECT_GALLERY_MAX_SAMPLES`, `G2_OBJECT_GALLERY_MAX_MB` | 200, 5, 200 | capacity limits of the object gallery |

On the Mac and in the tools:

| Switch | Default | What it does |
|---|---|---|
| `G2_DATA_DIR` | `~/g2_data` | the Mac's real-data store |
| `G2_CAL_POLICIES` | the frozen reference and the newest final policy | the policies a calibration must not harm (the harm check) |
| `G2_REMOTE_MEMORY_DB` | `.local/share/g2/g2_memory.db` | the memory database `g2membackup` copies, relative to the Pi user's home |
| `G2_REVIEW_NO_OPEN` | unset | set it to stop the review page (`g2pics`, `g2pimem`) from opening a browser |
| `G2_VISION_CLASSES` | unset | the class order for the vision library, e.g. `a,b,dog,cat`; the real names are personal, so set it in your shell, not in the repo |
| `G2_CAM_PORT`, `G2_CAM_AEBUMP`, `G2_CAM_IDLE_EXIT` | first camera port, `0x30`, 10 | the camera preview: serial port, auto-exposure lift (0 disables) and the idle-exit seconds |
| `G2_ROOT` | the repo | set by the aliases; `install_voice_service.sh` defaults it to `~/bittleX` on the Pi |

See also [`feature-flags.md`](feature-flags.md) for the `G2_FEATURES` subsystem flags.
