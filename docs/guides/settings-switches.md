# Settings and switches (environment variables)

Set in the Pi's `.env` (never `cat` that file; add a line with `echo 'KEY=value' >> .env`, restart the service) or in the environment of a one-off command. Defaults are what the code does with no setting.

Sounds
------

- `G2_SPEAKER_SOUNDS`: Default: on for the Pi, off on a dev machine; What it does: `1` plays speaker sounds on any machine (audition only; the volume is a tiny fraction of full scale)
- `G2_REFUSE_SOUND`: Default: on; What it does: the losing horn when he refuses a request (a gait he cannot switch to)
- `G2_FAIL_SOUND`: Default: on; What it does: the losing horn when a command fails (once per 8 s)
- `G2_FALL_HORN`: Default: on; What it does: the losing horn when he tips over (tilt past 60 degrees for 0.3 s), walking or not
- `G2_GRUNT`: Default: on; What it does: the grunt when you rebuff him
- `G2_COMPLETE_SOUND`: Default: on; What it does: the ta-da at the end of an exploration, and once when a goal session finishes normally (all attempts, the target or the time; not after a fall, a stop, the battery or a silent board)
- `G2_WALL_SOUND`: Default: on; What it does: the two-note turn-away sound
- `G2_HIT_SOUND`: Default: on; What it does: the long "ooooof" when he hits a wall
- `G2_ACK_TONE`: Default: `short_tone`; What it does: what acknowledges a command sent to Claude: `short_tone`, `ack_whistle`, `buzzer`, `off` (`star_trek_whistle` still works)
- `G2_FOLLOW_UP_S`: Default: 3; What it does: seconds the mic stays open after a reply (0 = no window, so no closing notes); `G2_QUESTION_WINDOW_S` (3) after a question

Exploration and walls
---------------------

- `G2_EXPLORE_ROAM_S`: Default: 600; What it does: the roam time of a voice-started exploration
- `G2_EXPLORE_HANDOVER`: Default: on; What it does: `0` stops "explore" from handing over to an exploration session
- `G2_EXPLORE_REQUEST`: Default: on; What it does: G2 asks "Can I go exploring?" after idling in the voice service and walks only on a yes. `0` turns the asking off
- `G2_EXPLORE_ASK_AFTER_S`: Default: 180; What it does: seconds of idling before G2 asks. A no or no answer doubles the wait, up to an hour
- `G2_WALL_STEER`: Default: on; What it does: `0` turns off wall steering (and the 3 s looks)
- `G2_HIT_WALL`: Default: on; What it does: `0` turns off the hit-a-wall sequence
- `G2_WALL_DRYRUN`: Default: on; What it does: `0` turns off the wall estimator and its log entirely
- `G2_PLACE_LOG`: Default: on; What it does: `0` stops the place-memory record of survey stops (`place_stops.jsonl` beside the exploration pictures)
- `G2_REFLECT`: Default: `dry`; What it does: Reflection on his own experience (one Claude call per new exploration session): `off`; `dry` logs the notes it WOULD save to `~/.local/share/g2/reflections_dry.jsonl`; `on` saves them as facts (source "experience")
- `G2_EXPERIENCES`: Default: `~/.local/share/g2/experiences.jsonl`; What it does: Where the per-session exploration recaps are kept (on the Pi)
- `G2_MEMORY_CALL_LOG`: Default: `~/.local/share/g2/memory_calls.jsonl`; What it does: The record of every memory-processing call (tidy-up and reflection): `python -m pi_pipeline.memory calls [--days N]`
- `XIAOZHI_MCP_ENDPOINT`: Default: unset; What it does: The AI head agent's secret MCP access-point address (`wss://…`), from the xiaozhi.me console. Only in the Pi's `.env`, never in chat, logs or the repo. `python -m pi_pipeline.head` connects to it and offers the head's model a few harmless tools
- `G2_WALL_LOOK_SLOW_S`: Default: 6; What it does: the look interval when no wall was seen within 40 in in the last 20 s (3 s otherwise)
- `G2_INTEREST_EVERY_S`: Default: 3 with steering, else 10; What it does: the look interval (overrides the above)
- `G2_PICTURE_PREP_EVERY_S`: Default: 0; What it does: camera warm-up for every picture (0) or only every N seconds
- `G2_SURVEY_COOLDOWN_S`, `G2_SURVEY_FIRST_S`: Default: 60, 30; What it does: at most one picture stop this often; the first after this long
- `G2_WALL_CAL`, `G2_WALL_LOG`, `G2_WALL_PICS`: Default: under `~/.local/share/g2/`; What it does: calibration file, look log, ring of near-wall pictures
- `G2_WALL_PICS_DIR`: Default: `~/g2_wall_pics`; What it does: where `wall_pictures` saves the recognition shots

Power and battery
-----------------

- `G2_SLEEP_AFTER_S`: Default: 300; What it does: seconds at rest before power-saving sleep (0 = off); the wake word wakes him with a yawn
- `G2_BATTERY_LOW_V`, `G2_BATTERY_CRITICAL_V`: Default: 7.54, 7.46; What it does: G2 pack alarms at rest (about 30% and 20%); `G2_BATTERY_LOAD_LOW_V` 7.3 and `G2_BATTERY_LOAD_CRITICAL_V` 7.2 under load
- `G2_PI_WARN_FRACTION`, `G2_PI_CRITICAL_FRACTION`: Default: 0.70, 0.80; What it does: Pi battery alarms as a share of the measured runtime (3.28 h); critical backs off to every 15 min
- `G2_POWER_LOG`: Default: `~/.local/share/g2/power_log.jsonl`; What it does: the power diary

Walking and standing
--------------------

- `G2_STAND_RAMP_S`: Default: 0.8; What it does: the eased stand-up (`off` / 0 = the old single jump; tests turn it off)
- `G2_TRANSITION_RAMP_S`: Default: 2.0; What it does: the longest eased move into a firmware skill's first frame (`link/transitions.py`)
- `G2_EASE_PICTURE_POSES`: Default: off; What it does: `1` eases the bow, look up and check like every other skill (`link/transitions.py`); off by default because the eased poses are too slow
- `G2_POSE_BALANCE`: Default: on; What it does: every pose (a firmware skill that is not a gait, the stand, lying down or calibration) plays with the firmware gyro balance on
- `G2_WAKE_LOG`: Default: `~/.local/share/g2/wake_triggers.jsonl`; What it does: every wake trigger and what followed it, for counting false triggers (`python -m pi_pipeline.voice.wake_log --days 7`); `off` turns it off
- `G2_WAKE_MIN_CONF`: Default: 0.6 (0 turns the check off); What it does: a wake phrase Kaldi is less sure of than this (0 to 1, lowest word confidence) is ignored
- `G2_EXPLORE_INPROCESS`: Default: 0; What it does: `1`: "go ahead and look around" runs the exploration inside the voice service (same link, walker, memory, speech engine and microphone; no (see below)
- `G2_FLOOR_TRIM_MAX_AGE_H`: Default: 12; What it does: a floor label older than this is not used to pick a per-floor trim (`g2attach floor-trim`); the general trim applies
- `G2_BODY_STATE`: Default: `~/.local/share/g2/body_state.json`; What it does: how the body has been doing (low battery, a recent fall, the last exploration), folded into each Claude turn's mood hint and the idle timing (`personality/body.py`); `off` turns it off
- `G2_FLOOR_PROMPT_S`: Default: `10`; What it does: how long G2 listens for the answer when he asks "What surface will I be walking on?" before a voice-armed roam (0 turns the question off)
- `G2_FLOOR_MAX_AGE_H` / `G2_FLOOR_SKIP`: Default: `1` / `0`; What it does: `tools/g2_explore.sh start` and `stationary` ask for the floor on a terminal when the label is unknown or older than this many hours; with no terminal the start is refused (set it with `g2floor tile`) unless `G2_FLOOR_SKIP=1`
- `G2_WAKE_MAX_BEFORE`: Default: unset (off); What it does: a wake phrase with more than this many other words before it in the same utterance is ignored (talk nearby, not a call); `wake_log` prints the words-before counts for real and false triggers and a suggested `G2_WAKE_MIN_CONF`
- `G2_MIC_WATCHDOG`: Default: 1; What it does: a supervised keeper reopens the microphone stream when no audio block has arrived for 6 s (backlog B27); `0` = off
- `G2_SPEECH_CACHE`: Default: `~/.cache/g2/speech`; What it does: disk cache of synthesised speech lines, so a line said before costs no synthesis (the exploration speech lag); `off` turns it off
- `G2_SPEECH_PREWARM`: Default: 1; What it does: a minute after the voice service starts, make the fixed exploration narration lines into the cache at low priority; `0` = off
- `G2_SURVEY_AFTER_WALL`: Default: 1; What it does: a finished wall turn-away is also a place for a survey picture (same cooldown); `0` = surveys only at the end of a clean leg
- `G2_SURVEY_EXTRA_FRAMES`: Default: 2; What it does: a survey picture takes this many more frames half a second apart and keeps the sharpest (local edge measure); `0` = one frame
- `G2_SURVEY_RELAX_S`: Default: 60; What it does: after this many seconds with no survey picture the "far from a wall" and "something interesting" requirements are lifted; `0` = never
- `VISION_SENSOR_OPT`: Default: 1 (0 in exploration); What it does: the camera's capture option for detection (0 = 240, 1 = 480); exploration sessions use 0, the picture option, so a picture needs no capture-mode switch
- `G2_PROFILE`: Default: 0; What it does: `1` runs a sampling profiler during an exploration session (`diag/sampler.py`): which threads use the CPU and where; the report is `profile.txt` in the session's diagnostics folder
- `G2_TRANSITION_READ_POSE`: Default: off; What it does: stage 2 of the eased transitions: after a firmware gait or a trick (pose unknown) the link reads the servos (`f`, two agreeing rows) and eases from the measured pose; off until `python -m pi_pipeline.link.check_serial posecheck` passes on G2
- `G2_WALK_RAMP_S`: Default: 0; What it does: opt-in speed ramp-in at the start of a policy walk, in seconds (the sim check showed no gain)
- `G2_FOOT_TRIM`: Default: policy default; What it does: `off` disables the foot trim (V6 default `fl=-0.3`)
- `G2_ANNOUNCE_ONLINE`: Default: on; What it does: `off` silences "G2 online."

- G2_TRANSITION_RAMP_S: a move takes as long as its fastest joint needs to stay under 80 deg/s (at least 0.25 s; the bow, look up and check are not eased), sent 40 times a second; `off` / 0 = the firmware's own jump; tests turn it off
- G2_POSE_BALANCE: `gB` just before it, after its ease; the stand guard sends `gb` once he has been still for its quiet window (`link/transitions.py`, `gait/stand_guard.py`). On by default, because the pod swinging tipped G2 in poses that ran with balance off; `0` goes back to balance off
- G2_WAKE_MIN_CONF: 0 = off. Every trigger logs its confidence (`journalctl -u g2-voice \| grep "wake word"`); pick the value once real calls and background talk separate
- G2_WAKE_MIN_CONF: Raise it for fewer false triggers, lower it if he stops hearing you. The look-alikes “gg”, “gee gee” and similar never wake him.
- G2_EXPLORE_INPROCESS: `1`: "go ahead and look around" runs the exploration inside the voice service (same link, walker, memory, speech engine and microphone; no stop and restart of `g2-voice`, no second Piper/Vosk load). Needs `explore`, `vision` and `vision_safety` on in the service's own `G2_FEATURES`; otherwise, or at `0`, the separate `g2-explore` session runs as before. Not yet tried on G2
- G2_FLOOR_PROMPT_S: Asked when the floor label is unknown or older than `G2_FLOOR_PROMPT_MAX_AGE_H` (default `1` hour); answer a floor ("tile") or "same"; no answer never blocks the roam


Exploration pictures, contact and one-sound-at-a-time
-----------------------------------------------------

- `G2_SURVEY_CLAW`: Default: auto; What it does: with the arm fitted every look is the claw look (attention pose, claw up, left, right and centre pictures, claw down, stand) (see below)
- `G2_AVOID_CHIRP`: Default: off; What it does: `1` brings back the soft chirp when he turns away from a wall (off by default)
- `G2_POSE_GATE`: Default: on (unproven); What it does: before a move that follows a pose change, and before a pose change shortly after a move, the body's real tilt is checked and lagging legs are re-seated; `0` turns it off (see `plan-detail/falls-at-transitions-2026-11-06.md`)
- `G2_STOP_CALM`: Default: on (unproven); What it does: a firmware move waits up to 0.4 s for a calm moment before its stop; `0` stops immediately as before
- `G2_LEG_CORRECT`: Default: on (unproven); What it does: a leg joint the board holds off its stand angle after a stand-up is driven back to it (just those joints, read back); `0` reports only
- `G2_CYCLE_STOP`: Default: off (unproven); What it does: a timed firmware turn or back-up runs on to the next whole gait cycle (at most 0.8 s longer) before its stop; period from `gait_cycles.json` (`transition_drill --measure`), `G2_GAIT_CYCLE_S`, or the move's own IMU frames
- `G2_PREPOSITION`: Default: off (unproven); What it does: before a firmware turn or walk the Pi eases the legs to the skill's first frame itself, even where the link does not know the pose
- `G2_EASED_STOP`: Default: off (test); What it does: the normal end of a timed turn or back-up freezes the legs at the gait's estimated pose and eases to balance (0.8 s at most) before `kbalance`; never for an emergency stop; needs a gait period
- `G2_ORT_ARENA`: Default: off; What it does: `1` puts back onnxruntime's memory arena for Piper and the embedder (the default frees about 20 MB once Piper has spoken, same speed)
- `G2_MALLOC_ARENAS`: Default: unset (one arena); What it does: `many` leaves glibc's default of several malloc arenas in the voice service; the single arena keeps a model reloaded on a background thread from ending up bigger
- `G2_RELEASE_VOICE`: Default: on; What it does: an in-process goal session or exploration roam frees Piper's memory (about 155 MB) at its start and loads it again in the background at its end
- `G2_GAIT_CYCLE_S`: Default: unset; What it does: one gait period in seconds (0.25-2.0) for every gait: overrides the measured file
- `G2_LEG_CHECK`: Default: on; What it does: after a stand-up from the attention pose or a sit the board's believed leg angles are compared with the stand pose and logged to `~/.local/share/g2/leg_check.jsonl` (report only); `0` turns it off
- `G2_SURVEY_CHECK`: Default: on; What it does: a survey stop is look up, look down, stand, firmware `check` (`kck`, the body lean; G2 has no head to pan), stand, settle, one picture; `0` skips the check
- `G2_SURVEY_LOOKS`: Default: off; What it does: `1` adds left and right turns with a throwaway picture each (open-loop turns were off by 30 to 70 deg)
- `G2_NEAR_LOOK_IN`: Default: 30; What it does: a wall this close (inches) starts the fast 3 s wall looks and blocks surveys and object checks for 20 s
- `G2_SURVEY_FIRST_S`, `G2_SURVEY_COOLDOWN_S`, `G2_INTEREST_FALLBACK_S`: Default: 30, 60, 300; What it does: survey pacing; the fallback is a random 0.6 to 1.4 times this
- `G2_WALL_KEEP_ALL`: Default: off; What it does: `1` keeps a picture of every wall look (a hit test); `tools/g2_explore.sh` passes it through
- `G2_IMU_CONTACT`: Default: on; What it does: the walk loop's heading-jitter signal (6 deg per IMU update over 3 s, 8 samples) starts the hit sequence (oof, back up, turn) even when vision says clear
- `G2_CONTACT_PICS`, `G2_CONTACT_PICS_DIR`: Default: on, `~/.local/share/g2/contact_pictures`; What it does: two instant frames at a stall or hit, for diagnosis only
- `G2_STALL_LOG`: Default: on; What it does: log-only 8 s stall detector (`imu.stall_suspect`)
- `G2_AUDIO_GATE`: Default: on; What it does: speech, sound effects and BiBoard beeps wait for each other (up to 4 s, then a safety sound cuts in)
- `G2_NARRATE_START_QUIET_S`: Default: 8; What it does: no narration for the first seconds of an exploration
- `G2_WALL_STEER`: Default: on; What it does: `0` turns the wall turn-away off (used to let him walk into a wall and test the hit sequence)

- G2_SURVEY_CLAW with the arm fitted every look is the claw look (attention pose, claw up, left, right and centre pictures, claw down, stand) instead of the bow, the sit and the check pose; `1` forces it, `0` brings the old looks back
- G2_RELEASE_VOICE: a line that needs synthesis during the session loads it first (about 10 s); `0` keeps it loaded


Locations, logs and limits
--------------------------

Where G2 keeps things, and the limits people occasionally change. The variables not listed here are printed by `python tools/gen_env_reference.py`.

- `G2_API_LOG`: Default: `~/.local/share/g2/api_calls.jsonl`; What it does: the log of every Claude API call (one JSON line each); `off` turns it off. Read with `g2api`
- `G2_API_PRICE`: Default: `2,10`; What it does: input and output dollars per million tokens, used for the cost estimate (Sonnet 5.5's list price); set it to match the model in use
- `G2_STOP_MIN_CONF`: Default: `0.5`; What it does: while the wake word is off (`g2mic off`), G2 listens only for the stop phrases
- `G2_GOAL_INPROCESS`: Default: `1`; What it does: goal sessions (`g2ball`, "G2, ball goal") run inside the running voice service, borrowing its serial link, IMU stream and camera, so the (see below)
- `G2_DROP_FRAGMENTS`: Default: `1`; What it does: a turn of one or two filler words ("yeah", "ah", "the") right after the wake word is dropped with no reply and (see below)
- `G2_PLACES`: Default: `~/.local/share/g2/places.json`; What it does: the places memory: per room, counts only (no dates or times) of things seen, falls and bumps, sessions, pictures and the floor
- `G2_CURRENT_PLACE`: Default: `~/.local/share/g2/current_place`; What it does: the room G2 was told he is in ("you're in the kitchen", or `python -m pi_pipeline.memory place kitchen`); explorations, goal sessions and pictures are filed under it for 6 hours, then it lapses
- `G2_GOAL_LESSONS`: Default: `0`; What it does: `1` saves each goal session's notes as memory facts again (they were a pile of near-repeats)
- `G2_LOG_DAYS`: Default: `7`; What it does: the command, noise, power, memory and wall debug logs keep this many days (checked at service start and daily); `0` keeps everything
- `G2_PROMPT_CACHE`: Default: `1h`; What it does: the part of every Claude request that never changes (tool list and system prompt, about 2,500 tokens) is cached and billed at (see below)
- `G2_RECALL_MAX_CHARS`: Default: `2400`; What it does: the memory notes of ONE request, in characters (about 4 per token)
- `G2_API_DAILY_USD`: Default: `2.0`; What it does: a daily ceiling on Claude spend, worked out from the API call log
- `G2_USAGE_FILE`: Default: `~/.local/share/g2/api_usage.json`; What it does: per-day call and token counts, including retries (`python -m pi_pipeline.voice.usage`)
- `G2_BATTERY_WATCH`: Default: on; What it does: the low-battery watch for G2's pack; `0` turns it off
- `G2_BATTERY_LOG`, `G2_BATTERY_LOG_EVERY_S`: Default: `~/.local/share/g2/battery_voltage.csv`, 300; What it does: the pack-voltage history, one line per interval (an empty path turns it off)
- `G2_PI_RUNTIME_LOG`: Default: `~/.local/share/g2/pi_runtime.json`; What it does: the measured Pi battery runs
- `G2_AUTOLOG_DIR`: Default: `~/g2_runs/auto`; What it does: where the automatic walk logs go
- `G2_RUNS_DIR`, `G2_LOG_DIR`: Default: `~/g2_runs`, `~/g2_logs`; What it does: walk logs and diagnostics sessions; both are tidied after `G2_TIDY_DAYS`
- `G2_CAP_DIR`: Default: `~/g2_cap`; What it does: the camera preview's captures, cleared at every voice-service start (pull them first with `g2pcam-pull`)
- `G2_DETECTION_LOG_DIR`: Default: `~/g2_runs/detections`; What it does: the detection log folder
- `G2_EXPLORE_PICTURES_DIR`: Default: `~/.local/share/g2/explore_pictures`; What it does: the exploration pictures
- `G2_NOISE_LOG`: Default: `~/.local/share/g2/noise.jsonl`; What it does: the log of BiBoard commands that make a noise; `off` turns the file off
- `G2_GAIT_MODE_FILE`, `G2_GALLERY_PENDING`: Default: `~/.local/share/g2/gait_mode.json`, `.../gallery_pending.json`; What it does: the shared gait mode and the pictures queued for the object gallery
- `G2_STATE_DIR`: Default: `~/.local/share/g2`; What it does: where `bringup` keeps its progress file
- `G2_DEFAULT_GAIT`: Default: `firmware` (`policy` selects the learned walk); What it does: `firmware`: walks are Petoi's scripted gait (`kwkF`, played as `wkArmF` on the arm): the voice service makes no learned walker, and the (see below)
- `G2_GYRO_BALANCE` (and `G2_EASING`, `G2_BLENDING`, `G2_GAIT_SWITCHING`, `G2_SKILLS`, `G2_FALL_RECOVERY`): Default: unset (the fitted attachment's profile decides); What it does: `0` / `1` overrides that attachment profile flag for one run, so a hardware A/B needs no profile edit or deploy
- `G2_GYRO_GAITS`: Default: off (experiment); What it does: `1`: the firmware gyro balance is switched on (`gB`, then a 0.3 s gap, `G2_GYRO_GAIT_GAP_S`) just before a scripted gait and stays (see below)
- (no switch) the stand-up: Default: always the eased `K` skill on the arm build; What it does: **Hard rule:** every stand-up is the board-played eased `K` skill, from rest, a sit, the attention pose or the pose the board reports
- `pi_pipeline/motion_feel.py` (and `G2_STAND_STEPS`, `G2_STAND_SPEED`, `G2_STAND_PAUSE`, `G2_STAND_WAIT_S`, `G2_CLAW_DEG_S`, `G2_CLAW_STEPS_PER_S`; override file `~/.local/share/g2/motion_feel.json` on the Pi): Default: the numbers in that file; What it does: how slow moves feel: the `K`-skill stand-up's stages, speed, pause and wait, and the claw raise's speed and step rate. The file explains each number
- `G2_MOTION_EVENTS`: Default: on (`~/.local/share/g2/motion_events.jsonl`); What it does: one line per stand-up: the pose the board reported before it, whether he was laid in rest first (an unknown or unreadable (see below)
- `G2_ATT_STAND`: Default: `smooth` ; What it does: the stand-up from the attention pose is one motion: the front legs start 0.35 s after the back legs (when they are (see below)
- `G2_CONVERSATION_WINDOW_S`, `G2_CONVERSATION_MAX_S`: Default: 20, 600; What it does: conversation mode ("let's talk"): how long G2 waits for you to start each turn, and the session limit; 0 for the window turns the mode off
- `G2_CONVERSATION_MAX_WORDS`, `G2_SIDE_MAX_WORDS`: Default: 30, 14; What it does: a turn heard without the wake word that runs longer than this is dropped before Claude (the first number applies in conversation mode); 0 means no limit
- `G2_VOLUME`: Default: 65; What it does: the one volume, percent of max, for every sound G2 plays (his voice, the tones, the alarms, the camera sounds) and the buzzer (65 -> `b6`); held to 75. No sound has a level of its own
- `G2_MEMLOG`, `G2_MEMLOG_S`: Default: `~/.local/share/g2/memory_log.jsonl`, 10; What it does: the memory log (`g2mem`): its file (`off` turns it off) and the seconds between readings
- `G2_TASK_SCOPE_STRICT`: Default: off (on in the tests); What it does: `1` makes a task that changes a setting it did not declare raise (util/task_scope.py)
- `G2_BATTERY_STRICT`: Default: off; What it does: `1` stops a test when the pack cannot be read (default: warn and go on)

- G2_STOP_MIN_CONF: A stop phrase counts only when the recogniser has finished the sentence, the whole sentence is the phrase, and every word has at least this confidence (0 = no confidence check). A stop heard then while G2 lies at rest is ignored, not announced. Noise used to be taken for "abort" and "halt" and he said "Stopping." over and over
- G2_GOAL_INPROCESS: goal sessions (`g2ball`, "G2, ball goal") run inside the running voice service, borrowing its serial link, IMU stream and camera, so the port to the BiBoard is never closed. `0` = the old hand-over: the service is stopped, the session runs on its own, the service is started again (also `g2goal run GOAL --standalone`). Needs a serial link and a camera in the service, else it falls back by itself
- G2_DROP_FRAGMENTS: a turn of one or two filler words ("yeah", "ah", "the") right after the wake word is dropped with no reply and no saved record, and in the follow-up window (no question asked) a single word or filler pair is dropped too. `0` turns the filter off. Half of the wake triggers logged in one week were false, which is why it exists
- G2_PLACES: short summaries reach the prompt when a room is mentioned or asked about. `python -m pi_pipeline.memory place list` shows it
- G2_GOAL_LESSONS by default the notes stay in the journal and ONE `goal_summary` fact per goal is kept, shown in chat only when the ball, a goal or practice comes up
- G2_PROMPT_CACHE: the part of every Claude request that never changes (tool list and system prompt, about 2,500 tokens) is cached and billed at a tenth of the input price on a hit: `1h`, `5m` or `off`. The mood, narration and gait hints sit after the cached part so changing one never resets it. `g2api` shows the tokens read from the cache
- G2_RECALL_MAX_CHARS: Over it the lowest-ranked facts go first, then past moments; the core facts stay. `0` = no limit. Notes are sent with their own request only, never repeated in the history
- G2_API_DAILY_USD: A warning in the log at 80%; at the ceiling G2 says he has used up his thinking budget and makes no more Claude calls until midnight (moves and stop words still work). `0` = no ceiling. The busiest day so far cost $0.44. `g2api` ends with today's figure
- G2_DEFAULT_GAIT: `firmware`: walks are Petoi's scripted gait (`kwkF`, played as `wkArmF` on the arm): the voice service makes no learned walker, and the chase and the exploration walk with it (no bump signal from the walk); `policy` brings the learned walk back
- G2_GYRO_BALANCE (and G2_EASING, G2_BLENDING, G2_GAIT_SWITCHING, G2_SKILLS, G2_FALL_RECOVERY): The arm's stand-up ramp turns the gyro balance off for the ramp and on again after it, where it is switched on by name
- G2_GYRO_GAITS: `1`: the firmware gyro balance is switched on (`gB`, then a 0.3 s gap, `G2_GYRO_GAIT_GAP_S`) just before a scripted gait and stays off otherwise (the stop `kbalance` is followed by `gb` as before), so it is never on in the attention / sit poses, where the board took a pose for a fall and flipped him with its own `rc` / `up`
- (no switch) the stand-up: `G2_STAND_VIA`, the profile's `stand_via` and `motion_feel` can no longer bring back the firmware or the Pi-streamed stand-ups. The numbers (stages, speeds, wait, gyro during the rise) are in `pi_pipeline/motion_feel.py`. If it cannot run, G2 does not stand and the command is dropped
- G2_MOTION_EVENTS: one line per stand-up: the pose the board reported before it, whether he was laid in rest first (an unknown or unreadable pose gets `krest` then the stand-up), the numbers, the seconds and how it ended (`reached` / `forced` / `refused`). `off` disables it; another value is the file to use. Read by `python -m pi_pipeline.diag report` helpers (`diag/run_report.py`)
- G2_ATT_STAND: the stand-up from the attention pose is one motion: the front legs start 0.35 s after the back legs (when they are about a fifth up) instead of 0.9 s, the whole leg pose is re-sent every 4 steps so a dropped joint is corrected within about 0.3 s; `legacy` keeps the two-stage stand-up (back legs 85% up before the front legs start)


**One volume for everything**: every sound G2 plays, his voice included, comes out at `G2_VOLUME` (default **65% of max**, `pi_pipeline/sound_levels.py`), and the buzzer is set to match (6 of 10). No sound has a level of its own; nothing is ever louder than 75% of max.

- `G2_MEMORY_LOG_COMMANDS`: default off; `1` logs the memory-related spoken commands
- `G2_NARRATE_HIDE_NAMES`: default off; `1` makes G2 say "someone" instead of the names he knows when narrating
- `G2_INTEREST`: default on; `0` turns off the interest watch that decides when an exploration stop is worth a picture
- `G2_WALL_LOOK_FAST_S`: default 3; seconds between wall looks while a wall is near
- `G2_OBJECT_GALLERY_MAX_ENTRIES`, `G2_OBJECT_GALLERY_MAX_SAMPLES`, `G2_OBJECT_GALLERY_MAX_MB`: default 200, 5, 200; capacity limits of the object gallery

On the Mac and in the tools:

- `G2_DATA_DIR`: Default: `~/g2_data`; What it does: the Mac's real-data store
- `G2_CAL_POLICIES`: Default: the frozen reference and the newest final policy; What it does: the policies a calibration must not harm (the harm check)
- `G2_REMOTE_MEMORY_DB`: Default: `.local/share/g2/g2_memory.db`; What it does: the memory database `g2membackup` copies, relative to the Pi account's home directory
- `G2_REVIEW_NO_OPEN`: Default: unset; What it does: set it to stop the review page (`g2pics`, `g2pimem`) from opening a browser
- `G2_VISION_CLASSES`: Default: unset; What it does: the class order for the vision library, e.g. `a,b,dog,cat`; the real names are personal, so set it in your shell, not in the repo
- `G2_CAM_PORT`, `G2_CAM_AEBUMP`, `G2_CAM_IDLE_EXIT`: Default: first camera port, `0x30`, 10; What it does: the camera preview: serial port, auto-exposure lift (0 disables) and the idle-exit seconds
- `G2_ROOT`: Default: the repo; What it does: set by the aliases; `install_voice_service.sh` defaults it to `~/bittleX` on the Pi

See also [`feature-flags.md`](feature-flags.md) for the `G2_FEATURES` subsystem flags.
