# Punt: running the test and dialing in the settings

G2 chases the green treat ball and **punches** it once (the lunge of Petoi's pick skill with the claw held shut, so the claw hits the ball and does not try to grab it). A **punt test** is one
attempt: he stands up from rest, finds the ball, walks to it, punches it once, and goes back to rest. The operator watches, changes a setting if needed, and runs the next attempt.
Everything needed to dial in the punt is on this page.

- Distances are **inches from the camera to the ball**. The camera sits on the claw, so the jaws are about 1 in nearer than the camera reading.
- The values G2 uses live in **one file on the Pi**, read at the start of every run: change a value, run again, no deploy needed (section 4).

1\. Before every attempt
-----------------------

1. The Pi is on and has the current code (`g2deploy --once` from the Mac after a commit; see the end of this page).
2. G2 is lying in **rest** on the surface being tested, with a clear patch in front of him. On a desk, keep the nearest edge well away: he walks toward the ball and will not see an edge.
3. The ball is **straight ahead of him**, about 12 to 24 in away, on the same surface. A first attempt from about 12 in is a good start.
4. The surface label matches (`g2floor desk`, or `g2floor hardwood`).
5. The pack is charged (the run stops by itself under 30%; a dead pack drops the board).
6. A hand near G2. Stop any time with section 3.

2\. Run one attempt
------------------

By voice (G2 must be listening): say **"G2, punt"**. He says "Punting.", the voice service steps aside, and one attempt runs. He rests at the end and the voice service comes back.
Other phrases that work: "punt it", "punt the ball", "go punt", "do a punt", "punt test".

**From the Mac, no voice (same thing):**

```bash
g2punt                          # one attempt with the saved settings
g2punt --punt-max 3.5           # one attempt with one value changed just for this run
```

`g2punt` stops the voice service on the Pi, runs the attempt (its log shows on screen), rests G2, and starts the voice service again. It needs `G2_PI` set (the aliases from `tools/g2_aliases.sh`).

**On the Pi directly (ssh in), no aliases:**

```bash
ssh "$G2_PI"
sudo systemctl stop g2-voice                      # the camera and the serial port must be free
cd ~/bittleX && source pi_pipeline/.venv/bin/activate
rm -f ~/.local/share/g2/ball_chase_stop
PYTHONPATH=. python -u -m pi_pipeline.behavior.ball_chase --punts 1
# ... afterwards:
sudo systemctl start g2-voice
```

Useful extra flags on that command (each one overrides the same setting in the file for that run only): `--punt-max IN`, `--nudge-max IN`, `--nudges N`, `--max-seconds S`, `--dry-run` (looks and prints what it would do, no motion), `--use-pick` (the pick skill instead of the punch), `--search-walk` (walks on blind while searching: a big floor only, never a desk).

**One punch at each distance you choose (the ball is placed each time and the result reported):**

```bash
ssh -t "$G2_PI"                                   # -t: it asks questions
sudo systemctl stop g2-voice
cd ~/bittleX && source pi_pipeline/.venv/bin/activate
PYTHONPATH=. python -m pi_pipeline.behavior.punt_test                         # 2, 3, 4 and 5 in
PYTHONPATH=. python -m pi_pipeline.behavior.punt_test --distances 2.5 3 3.5 4 --repeat 2
```

For each distance it says where to put the ball, shows what the finder reads (to be checked against a tape measure), waits for Enter, punches once, and asks how far the ball
went and whether the claw hit it first. Every punch is a row in `~/g2_punt_tests.csv` on the Pi. Afterwards `sudo systemctl start g2-voice`.

3\. Stop an attempt
------------------

- From the Mac: `g2puntstop`.
- By voice: "G2, emergency stop" (the voice service may be stopped during a run; if so use the Mac command).
- On the Pi: `touch ~/.local/share/g2/ball_chase_stop` (he finishes the step he is on and rests), or Ctrl-C if it was started in a terminal.
- He also stops by himself on a fall, a pack under 30%, or after `max_seconds`.

What is heard: **"target acquired"** when he sees the ball (again), **"searching"** when he starts looking for it, **"punting"** right before the lunge.

4\. The settings: what they are, where they live, how to change them
------------------------------------------------------------

The file: `~/.local/share/g2/punt_settings.json` on the Pi. A missing file, or a missing line in it, means the default. It lives outside the repo, so **a deploy does not overwrite it**.
It is read at the **start of every run** (voice or not), so a change takes effect on the next attempt.

- `punt_max_in`: Default: 4.0; Allowed: 1 to 10; What it does and which way to change it: **The main one.** He punches when the ball is this close or closer. Punch too early (ball out of reach, claw misses): **lower** it. Walks into the ball before punching: **raise** it.
- `nudge_max_in`: Default: 7.0; Allowed: 1 to 12; What it does and which way to change it: From `punt_max_in` out to this distance he takes small steps closer before punching. Set it **equal to `punt_max_in`** for no small steps.
- `nudges_before_punt`: Default: 3; Allowed: 0 to 10; What it does and which way to change it: After this many small steps that did not get him in range he punches anyway.
- `nudge_step_s`: Default: 0.9; Allowed: 0.3 to 2.5; What it does and which way to change it: Length of one small step closer. Shorter = finer, but a walk covers nothing in its first 0.7 s or so.
- `nudge_gait`: Default: scripted; Allowed: scripted, policy; What it does and which way to change it: How the small steps closer (and the step closer after a punt) are walked
- `walk_aim_in`: Default: 4.0; Allowed: 1.5 to 8; What it does and which way to change it: The long walk steps are timed to leave the ball about this far away. Overshoots into the ball: **raise** it. Stops far away: **lower** it.
- `punt_align_deg`: Default: 12; Allowed: 2 to 30; What it does and which way to change it: The ball must be within this many degrees of straight ahead before the punch. Ball goes crooked: **lower**. He turns and turns and never punches: **raise**.
- `punch_lunge_s`: Default: 0.12; Allowed: 0.05 to 0.6; What it does and which way to change it: Seconds the lunge takes. Smaller = harder and faster.
- `punch_hold_s`: Default: 0.25; Allowed: 0 to 1; What it does and which way to change it: Seconds the lunge is held before he comes back.
- `lost_looks`: Default: 3; Allowed: 1 to 8; What it does and which way to change it: Looks in a row without the ball before he starts searching. He searches although the ball is there: **raise** it.
- `search_walk`: Default: false; Allowed: true / false; What it does and which way to change it: After a full search circle, walk on blind. **Leave false on a desk.**
- `max_seconds`: Default: 75; Allowed: 10 to 600; What it does and which way to change it: The attempt ends, and he rests, after this long.
- `search_order`: Default: claw_scan; Allowed: turn, claw_then_turn, claw_scan, back_claw_scan, claw_back_scan, back_turn, back_and_turn, three_point_turn, claw_three_point, full_circle, claw_full_circle; What it does and which way to change it: How he looks for the ball: claw looks (the arm points the camera, the legs stay), turn steps, back-ups, in that order
- `claw_look_pan_deg`: Default: 35; Allowed: 10 to 45; What it does and which way to change it: How far to each side a claw look points the camera
- `claw_look_lift_deg`: Default: 15; Allowed: 0 to 35; What it does and which way to change it: How high a claw look lifts the arm (higher sees farther; 0 = level).
- `claw_pan_sign`: Default: right; Allowed: right / left; What it does and which way to change it: Which way a positive arm pan turns the camera: right on G2 (from sweeps: pan +35 barely turns it, pan -35 about 39 deg left: `CLAW_PAN_SHARE`). Re-measure with `python -m pi_pipeline.behavior.claw_look --calibrate` ([`goals.md`](goals.md)).
- `scan_turn_deg`: Default: 60; Allowed: 20 to 90; What it does and which way to change it: One turn between two claw looks.
- `search_step_deg`: Default: 20; Allowed: 10 to 60; What it does and which way to change it: One turn step of a search without claw looks.
- `back_up_s`: Default: 2.0; Allowed: 0.5 to 4; What it does and which way to change it: One back-up (after stuck punts, and as a search move).
- `back_up_budget_s`: Default: 6.0; Allowed: 0 to 20; What it does and which way to change it: The most backing up in one attempt. **Keep it small, or 0, on a desk.**
- `stuck_punts`: Default: 3; Allowed: 1 to 6; What it does and which way to change it: Punts with the ball still in range before he backs up.
- `when_vanished`: Default: punt; Allowed: punt / back_up; What it does and which way to change it: The ball vanished up close: punch (it is at the claw) or back off a little to see it.
- `align_pulse_min_s`: Default: 1.0; Allowed: 0.3 to 1.6; What it does and which way to change it: Within 7 in and off line he lines the claw up with small turns, a picture after each: the shortest pulse
- `align_tries`: Default: 3; Allowed: 1 to 8; What it does and which way to change it: Small turns to line up before `when_misaligned`.
- `when_misaligned`: Default: punch; Allowed: punch / back_up; What it does and which way to change it: Still off line after `align_tries`: punch anyway or back up and line up again.
- `between_moves`: Default: stand; Allowed: stand / attention; What it does and which way to change it: While not moving: stand (the original flow), or wait in the attention pose (legs straight, the picture taken there) and stand up (see below)

- nudge_gait: `scripted` is Petoi's own forward walk (`kwkF`) for `nudge_step_s`, steadier than the learned policy for setting the distance; `policy` is the learned gait. The line-up turns are always Petoi's turns (`kwkL`/`kwkR`). The long walk toward a far ball stays the learned policy. A fixed setting: G2 never changes it. A scripted step is not used to measure the learned walk's pace. `nudge_step_s` values learned with the policy walk do not carry over, so they are checked after a switch.
- search_order: `claw_scan` = a claw look first, then a turn and a claw look, repeated. `full_circle` = turn steps counted up to one whole turn, then a back-up for a wider view if the back-up budget allows (`claw_full_circle` adds a claw look between the steps); in the simulator it scored the same as plain `turn`, and `claw_full_circle` among the worst. Every move he chooses, with the reason, what he saw, the planner state and the options passed over, is a line in `~/.local/share/g2/decision_log.jsonl` (`G2_DECISION_LOG`; stops growing at 50 MB).
- claw_look_pan_deg: A claw look is done from a sit: sit, arm left, picture, arm right, picture, arm to centre, stand up slowly with the back legs. It is only used while he has not seen the ball this attempt; once he has seen it he only takes straight pictures. Only the ball's direction is used from it (the sitting camera is lower), and a ball only the loose dim pass found must show again in a second picture.
- align_pulse_min_s: Each turn is stopped on the gyro once he has turned the planned 3 to 6 deg (40% of the bearing, `ALIGN_GAIN`); this time is only the fallback when no IMU frames arrive, and the cap is 2.5 s (a 1 s pulse turned G2 25 to 70 deg).
- between_moves: While not moving: stand (the original flow), or wait in the attention pose (legs straight, the picture taken there) and stand up back legs first to move (an alternative against the legs letting go after 7 to 10 s still; the standing flow is the default because it is more fluid). A fixed goal knob: G2 never changes it.


**Walls come first**: the chase never walks closer than `chase_wall_in` to a wall (10 in to start, learned by the walls goal, never below 4 in), turns away
when he is that close, leaves a ball lying nearer a wall than that, and stops a walk on a bump. It uses the camera's wall reading as it is (calibrating it is optional); with no
wall calibration at all the run prints "wall check: off". [`goals.md`](goals.md) section 8.

**Walking** follows the default gait: Petoi's scripted `kwkF` walk (`G2_DEFAULT_GAIT=firmware`, see [Status](../STATUS.md)), or the arm's saved learned gait policy when `G2_DEFAULT_GAIT=policy`. Each walk and turn is timed from the pace and turn rates G2 measures
himself from the camera (`~/.local/share/g2/chase_pace.json`, per attachment and floor). **In a goal session** ([`goals.md`](goals.md)) G2 changes most of these settings himself between
attempts, starting from the values in this file; he never writes to this file except when one of his suggestions is confirmed.

**Change a value (from the Mac):**

```bash
g2puntset                           # show the file's path and the value of every setting a run would use now
g2puntset punt_max_in 3.5           # change one value (checked first; a bad value changes nothing)
g2puntset init                      # create the file with every setting at its default (never overwrites)
```

Or edit it by hand on the Pi: `ssh "$G2_PI"`, then `nano ~/.local/share/g2/punt_settings.json`, change the number, save. The file is plain JSON (one `"name": value,` per line; keep the commas).
`cd ~/bittleX && PYTHONPATH=. pi_pipeline/.venv/bin/python -m pi_pipeline.behavior.punt_settings` prints what the next run will use and reports any line it did not accept (an unknown name or a value out of range is ignored and reported at the start of the run, never used silently).
Back to the defaults: delete the file (`rm ~/.local/share/g2/punt_settings.json`) or set a value back.

**Where the defaults are in the code** (only to change what "default" means): `pi_pipeline/behavior/ball_chase.py`, the constants near the top: `PUNT_MAX_IN`, `NUDGE_MAX_IN`, `NUDGES_BEFORE_PUNT`, `NUDGE_S`, `WALK_AIM_IN`, `PUNT_ALIGN_DEG`, `PUNCH_LUNGE_S`, `PUNCH_HOLD_S`, `LOST_LOOKS`, `SEARCH_WALK`, and the search, claw-look and alignment constants below them.
The list of settings, their limits and their descriptions is `SPEC` in `pi_pipeline/behavior/punt_settings.py`. The punch's own key poses (the shape of the lunge) are `punch_keys()` in `ball_chase.py`.
After editing code on the Mac: commit, then `g2deploy --once` (below). Do not edit the code on the Pi: the next deploy replaces it.

5\. Reading an attempt
---------------------

Each attempt ends with a line like:

```
ATTEMPT: punted at (2.7, 6.7) (in, deg) after 4 looks; walk steps (ball in, seconds): [(13.0, 2.2), (13.0, 2.3)]
```

- `punted at (2.7, 6.7)` when he punched, the finder read the ball 2.7 in away and 6.7° to the right of straight ahead. **This is the number to tune against**: compare it with how the punch went.
- `walk steps` for each long walk, how far away the ball was when he started it and how long he walked. If the ball distance is the same before and after a walk, that walk did not move him (known issue: the first walk after a stand-up sometimes covers nothing).
- If the run was started by voice, read it with `ssh "$G2_PI" journalctl -u g2-punt --no-pager -n 60`.

Measured so far: a ball 2.6 in from the camera threw 18 in straight ahead (claw hits it first); 4.5 to 5 in was just out of reach; 6 to 7 in too far; the first desk attempt punched at 2.7 in. The finder is only accurate to about 1 in at close range.

6\. A way to dial it in
----------------------

1. Start at the defaults, ball about 12 in ahead. Run one attempt.
2. Look at the `punted at` distance and what the punch did: did the claw hit the ball first, did it go straight, how far.
3. Change **one** setting (usually `punt_max_in` by 0.5 in) with `g2puntset`, run the next attempt. Keep a note of the setting and the result of each attempt.
4. Once the distance is right, tune the side effects: `punt_align_deg` for crooked punches, `walk_aim_in` for overshooting, `punch_lunge_s` for how hard.
5. For a clean table of distance against result, use `punt_test` (section 2): one punch at each fixed distance, the results in a CSV.

- He punches but the claw misses or barely touches the ball: lower `punt_max_in`
- He walks into the ball and pushes it before punching: raise `walk_aim_in`; raise `punt_max_in`
- He punches from far away and the ball does not move: lower `punt_max_in`
- Right in front of the ball and no punch: the ball is more than `punt_align_deg` off straight (raise it), or the finder lost it; run `--dry-run` and read what it says
- The ball goes sideways: lower `punt_align_deg`; check he was lined up
- He searches although the ball is in front of him: raise `lost_looks`; a ball in direct sun goes pale and the finder misses it (shade it or move it)
- The punch is weak or slow: lower `punch_lunge_s`
- He turns away from the ball: the ball is out of his view or too far to the side: start it straight ahead

7\. If something does not work
-----------------------------

- The board does not answer / G2 goes limp: check the plug between the Pi and the BiBoard first (it comes undone in falls), then the pack.
- "G2, punt" does nothing: the speech recognizer may not have heard the word; run `g2punt` from the Mac instead. The voice service's log: `ssh "$G2_PI" journalctl -u g2-voice -n 40`.
- After a run the voice service is not back: `ssh "$G2_PI" sudo systemctl start g2-voice` (or `g2reset`).
- Pictures: every picture with the ball found is saved with its box for the future ball detector (`g2pics`, Named: greenball).

8\. Deploying a code change to the Pi
------------------------------------

From the repo root on the Mac, after committing (it ships the last commit):

```bash
g2deploy --once            # deploy now if the Pi answers
g2deploy                   # wait up to 24 h for the Pi, then deploy
bash tools/g2_deploy_when_online.sh --once        # the same, without the alias
```

A deploy restarts the voice service, so it never changes the settings file, and it refuses to run during a walk. The settings file is the only thing to change to dial in the punt.
