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

See also [`feature-flags.md`](feature-flags.md) for the `G2_FEATURES` subsystem flags.
