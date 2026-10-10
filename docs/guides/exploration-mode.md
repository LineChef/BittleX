# Exploration mode: how it works

Exploration is G2 walking around a cleared area by himself, looking at things, taking pictures and keeping away from walls. It is voice-armed only and never starts on its own.
Code: `pi_pipeline/explore_session.py` (the session), `behavior/explore.py` (legs and headings), `behavior/driver.py` (the priority chain, wall steering, hit detection),
`behavior/survey.py` (picture stops), `behavior/interest_watch.py` (the peeks), `vision/wall_distance.py` (the wall estimator). Settings: [`settings-switches.md`](settings-switches.md).
Commands you can say: [`voice-commands.md`](voice-commands.md). Wall work and test history: [`../vision/wall-check-plan.md`](../vision/wall-check-plan.md).

## Starting it

- **By voice:** "G2, explore" (also "go ahead and look around", "exploration mode"). He says "Exploration mode.", waits 1 s, plays the Viking horn, and hands over: the voice service stops and
  a separate exploration session starts (about 30 s). The session lays him down first, then he stands with the eased stand-up and begins.
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
4. **Picture stops.** At the end of a leg, at most every 60 s (the first after 30 s), and only when something is worth it: look down (the bow), look up, stand again (eased stand-up), wait 3.3 s, wait until the IMU
   shows he has stopped swaying (up to 6 s), warm the camera up and meter the light, take the picture (retaken once if it is too dark or bright), walk on. Pictures: `~/.local/share/g2/explore_pictures/`,
   reviewed with `g2pics`.
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
| a command fails | the losing horn |
| fell over | the losing horn |
| end | "Exploration complete.", the ta-da, he lies down; "G2 online." when the voice service is back |

## Ending it

The roam time runs out (the end of the cap always ends the whole session), or you say "that's enough" / "end exploration mode" / "cancel exploration", or "emergency stop", or `g2_explore.sh stop`.
However it ends (even a crash) the unit sends rest (`d`) before the voice service starts again.

## Where to look afterwards

- `journalctl -u g2-explore` on the Pi (or `bash tools/g2_explore.sh logs`): turns, `g2.wall.steer`, `g2.wall.hit`, chirps, pictures.
- `~/.local/share/g2/wall_dryrun.jsonl` and `python -m pi_pipeline.vision.wall_stats`: every wall look in inches, the state, the turn it would make, the saved near-wall pictures.
- `~/g2_runs/auto/<date>/`: the policy walk logs (CSV plus a JSON sidecar).
- `~/.local/share/g2/noise.jsonl`: every command sent to the BiBoard, with the source that sent it.

## Known limits (2026-10-10)

The wall estimator is a prototype: readings are good to 2 to 4 in between 8 and 24 in and only say far from near beyond that; glossy floor and bright patches can fool it; the camera is rolled about 4 degrees
(not corrected, by decision), so left and right are a little biased; the left 45 degree wall was never seen clearly; there is no edge or step detector. The pictures behind it are a prototype set (some
overexposed) to be retaken. Test it with a person next to G2.
