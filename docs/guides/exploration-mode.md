# Exploration mode: how it works

Exploration is G2 walking around a cleared area by himself, looking at things, taking pictures and keeping away from walls. It is voice-armed only and never starts on its own.
Code: `pi_pipeline/explore_session.py` (the session), `behavior/explore.py` (legs and headings), `behavior/driver.py` (the priority chain, wall steering, hit detection),
`behavior/survey.py` (picture stops), `behavior/interest_watch.py` (the peeks), `vision/wall_distance.py` (the wall estimator). Settings: [`settings-switches.md`](settings-switches.md).
Commands you can say: [`voice-commands.md`](voice-commands.md). Wall work and test history: [`../vision/wall-check-plan.md`](../vision/wall-check-plan.md).

## Starting it

- **By voice:** "G2, explore" (also "go ahead and look around", "exploration mode"). He says "Exploration mode.", waits 1 s, plays the Viking horn, and hands over: the voice service stops and
  a separate exploration session starts (about 30 s). The session lays him down first, then he stands with the eased stand-up and begins.
- **In the voice service (opt-in, 2026-10-18, not yet tried on G2):** with `G2_EXPLORE_INPROCESS=1` the voice command runs the exploration inside the voice service instead: no stop and restart, no second load of the speech models, the same microphone; the service's stand guard, battery watch and sleep watch stand aside until it ends, then the voice loop carries on. It needs `explore`, `vision` and `vision_safety` on in the service's own `G2_FEATURES`; otherwise the separate session runs as above.
- **By script:** `bash tools/g2_explore.sh start [ROAM_S]` (default 600 s; `0` = no cap), or `stationary` for the stay-put mode. Status, logs and a clean stop: `status | logs | halt | stop`.
- Needs: a cleared area with no edges (there is no edge detector), G2 on his feet or at rest on the floor, the BiBoard powered, the pack not low. Never on a desk or the stand.
- Do not deploy to the Pi while a session runs: a deploy at the same moment as a crash left him circling (2026-10-10).

## Two tiers

| Tier | What | Starts |
|---|---|---|
| 0, attentive | stands still, turns toward sounds, follows faces with his gaze, reacts | always, as soon as the session is up |
| 1, roam | walks legs, looks, takes pictures, steers away from walls | armed by the start command; capped by the roam time |

## What a roam does

1. **Straight first.** For the first 8 s of a roam he walks straight ahead. Only then may the explorer turn (a wall turn is never held back).
2. **Legs.** Each leg is 8 s (`explore_leg_secs`) in one heading, then a short pause and a new heading (the stalest direction, scaled by `wander_turn_bias`). The policy walker (V6, trim `fl=-0.3`) does
   the straight walking; turns are timed firmware turns (left about 11 deg/s, right about 18 deg/s). A leg that has a wall ahead is cut to what is left before it:
   `(nearest wall - 12 in) / 3.5 in/s`, never under 1.5 s.
3. **Looks.** A cheap camera look (not saved, no API call) every 3 s while a wall was seen within 40 in in the last 20 s, otherwise every 6 s. The same look feeds the interest watch (is there an unknown
   object worth a picture stop?) and the wall estimator.
4. **Picture stops.** A survey stop is: look up (`ksit`), look down (the bow), stand, the firmware `check` lean, stand again, settle, then the picture. Before the shutter the body must stop swaying on the IMU (up to 6 s); the camera is warmed up and the light metered; the picture is the sharpest of three frames half a second apart (`G2_SURVEY_EXTRA_FRAMES`), retaken once if too dark or bright. A picture never holds him more than 10 s: after one 3 s retry he walks on and says "My camera isn't answering." Three kinds of stop:
   - **Scheduled:** every roam with a time cap takes four, at 25, 50, 75 and 99 percent of the roam, whatever the cooldown and gate say. Each waits up to 15 s for a good moment (a finished wall turn, so he faces open space, or the end of a leg), then happens where he is; the last one does not wait. They are never dropped as near-duplicates.
   - **After a wall turn or a clean leg end,** at most every 60 s (the first after 30 s), when the interest watch finds something worth it, or after 60 s with no picture at all (`G2_SURVEY_RELAX_S`; `G2_SURVEY_AFTER_WALL=0` turns the wall-turn trigger off).
   - **By voice:** "this is a <name>" takes a named picture.
   Interest peeks pause while a picture is being taken, and exploration detects at the camera's picture capture option so a picture needs no capture-mode switch. Pictures: `~/.local/share/g2/explore_pictures/`, reviewed with `g2pics`; the scheduled ones are `after_bow_m25` to `after_bow_m99`.
5. **Wall steering.** The estimator turns the picture's floor line into inches per column group (calibration in `~/.local/share/g2/wall_calibration.json`). A wall ahead means three of five groups at 24 in or
   closer on two of the newest three looks (about 50 degrees away, toward the side with more room), or any look at 12 in or closer, or a blocked picture. The turn replaces any turn already running, and a
   two-note falling sound plays so you know why he turned.
6. **Hit a wall.** A blocked look, a wall 6 in or closer on three groups, or two looks in a row at the same close wall with no turn between them: he says a long "ooooof", backs up for 2.4 s, stops, and
   turns around about 150 degrees toward the open side. Vision only for now; the IMU and servo-strain contact signals are still to build.
7. **Always on underneath.** The fall guard (a tilt past 60 degrees for 0.3 s plays the losing horn and rests him), the thermal guard, the battery watch (G2 pack alarms at about 30% and 20%), the watchdog
   (a stalled control loop rests him), and the emergency stop.

## Sounds you hear

| Moment | Sound |
|---|---|
| start | "Exploration mode.", 1 s, the Viking horn |
| turning away from a wall | two soft falling notes |
| hit a wall | a long "ooooof" |
| a picture is taken | the shutter double click |
| the camera does not answer | he says "My camera isn't answering." |
| a command fails | the losing horn |
| fell over | the losing horn |
| end | "Exploration complete.", the ta-da, he lies down; "G2 online." when the voice service is back |

## Ending it

The roam time runs out (the end of the cap always ends the whole session), or you say "that's enough" / "end exploration mode" / "cancel exploration", or "emergency stop", or `g2_explore.sh stop`.
However it ends (even a crash) the unit sends rest (`d`) before the voice service starts again.

## Where to look afterwards

- `journalctl -u g2-explore` on the Pi (or `bash tools/g2_explore.sh logs`): turns, `g2.wall.steer`, `g2.wall.hit`, chirps, pictures.
- `G2_PROFILE=1 bash tools/g2_explore.sh start 240` writes `profile.txt` in the session's diagnostics folder (`~/g2_logs/<session>/`): which threads use the CPU and where. Each walk's log sidecar (`~/g2_runs/auto/<date>/*.json`) records `late_ticks_pct` and `worst_tick_gap_ms`.
- **Narration** is fixed text chosen from what he does and sees (new leg, a wall about N inches ahead and which way he turns, a bump, straight starts); a local voice speaks it, no API call. Lines come at least 5 s apart, the same kind after 25 s. Since 2026-10-18 the synthesised lines are cached on disk (`~/.cache/g2/speech`, `voice/speech_cache.py`) and the fixed ones are made a minute after the voice service starts, so a session says them without synthesising; a line not ready 8 s after it was decided is dropped; each line logs `narration timing:` (queue, synthesis, play).
- `python -m pi_pipeline.diag report --html out.html` (on the Pi): the whole session on one page, including the speech lag, walks that did not stop in time and camera timeouts.
- After the session, its recap is kept in `~/.local/share/g2/experiences.jsonl` ("how was your exploration?"), saved as a memory sighting ("where's the chair?") and noted in the body state (`personality/body.py`).
- `~/.local/share/g2/wall_dryrun.jsonl` and `python -m pi_pipeline.vision.wall_stats`: every wall look in inches, the state, the turn it would make, the saved near-wall pictures.
- `~/g2_runs/auto/<date>/`: the policy walk logs (CSV plus a JSON sidecar).
- `~/.local/share/g2/noise.jsonl`: every command sent to the BiBoard, with the source that sent it.

## Known limits (2026-10-10)

The wall estimator is a prototype: readings are good to 2 to 4 in between 8 and 24 in and only say far from near beyond that; glossy floor and bright patches can fool it; the camera is rolled about 4 degrees
(not corrected, by decision), so left and right are a little biased; the left 45 degree wall was never seen clearly; there is no edge or step detector. The pictures behind it are a prototype set (some
overexposed) to be retaken. Test it with a person next to G2.
