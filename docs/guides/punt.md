# Punt: running the test and dialing in the settings

G2 chases the green treat ball and **punches** it once (the lunge of Petoi's pick skill with the claw held shut, so the claw hits the ball and does not try to grab it). A **punt test** is one
attempt: he stands up from rest, finds the ball, walks to it, punches it once, and goes back to rest. You watch, change a setting if it needs it, and run the next attempt.
Everything you need to dial in the punt is on this page.

- Distances are **inches from the camera to the ball**. The camera sits on the claw, so the jaws are about 1 in nearer than the camera reading.
- The values G2 uses live in **one file on the Pi**, read at the start of every run: change a value, run again, no deploy needed (section 4).

## 1. Before every attempt

1. The Pi is on and has the current code (`g2deploy --once` from the Mac after a commit; see the end of this page).
2. G2 is lying in **rest** on the surface you are testing on, with a clear patch in front of him. On a desk, keep the nearest edge well away: he walks toward the ball and will not see an edge.
3. The ball is **straight ahead of him**, about 12 to 24 in away, on the same surface. A first attempt from about 12 in is a good start.
4. The surface label matches (`g2floor desk`, or `g2floor hardwood`).
5. The pack is charged (the run stops by itself under 30%; a dead pack drops the board).
6. A hand near G2. Stop any time with section 3.

## 2. Run one attempt

**By voice (G2 must be listening):** say **"G2, punt"**. He says "Punting.", the voice service steps aside, and one attempt runs. He rests at the end and the voice service comes back.
Other phrases that work: "punt it", "punt the ball", "go punt", "do a punt", "punt test".

**From the Mac, no voice (same thing):**

```bash
g2punt                          # one attempt with the saved settings
g2punt --punt-max 3.5           # one attempt with one value changed just for this run
```

`g2punt` stops the voice service on the Pi, runs the attempt (you see its log on screen), rests G2, and starts the voice service again. It needs `G2_PI` set (the aliases from `tools/g2_aliases.sh`).

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

**One punch at each distance you choose (you place the ball each time and report the result):**

```bash
ssh -t "$G2_PI"                                   # -t: it asks you questions
sudo systemctl stop g2-voice
cd ~/bittleX && source pi_pipeline/.venv/bin/activate
PYTHONPATH=. python -m pi_pipeline.behavior.punt_test                         # 2, 3, 4 and 5 in
PYTHONPATH=. python -m pi_pipeline.behavior.punt_test --distances 2.5 3 3.5 4 --repeat 2
```

For each distance it tells you where to put the ball, shows what the finder reads (so you can check it against a tape measure), waits for Enter, punches once, and asks how far the ball
went and whether the claw hit it first. Every punch is a row in `~/g2_punt_tests.csv` on the Pi. Afterwards `sudo systemctl start g2-voice`.

## 3. Stop an attempt

- From the Mac: `g2puntstop`.
- By voice: "G2, emergency stop" (the voice service may be stopped during a run; if so use the Mac command).
- On the Pi: `touch ~/.local/share/g2/ball_chase_stop` (he finishes the step he is on and rests), or Ctrl-C if you started it in a terminal.
- He also stops by himself on a fall, a pack under 30%, or after `max_seconds`.

What you will hear: **"target acquired"** when he sees the ball (again), **"searching"** when he starts looking for it, **"punting"** right before the lunge.

## 4. The settings: what they are, where they live, how to change them

**The file:** `~/.local/share/g2/punt_settings.json` on the Pi. A missing file, or a missing line in it, means the default. It lives outside the repo, so **a deploy does not overwrite it**.
It is read at the **start of every run** (voice or not), so a change takes effect on the next attempt.

| Setting | Default | Allowed | What it does and which way to change it |
|---|---|---|---|
| `punt_max_in` | 4.0 | 1 to 10 | **The main one.** He punches when the ball is this close or closer. Punch too early (ball out of reach, claw misses): **lower** it. Walks into the ball before punching: **raise** it. |
| `nudge_max_in` | 7.0 | 1 to 12 | From `punt_max_in` out to this distance he takes small steps closer before punching. Set it **equal to `punt_max_in`** for no small steps. |
| `nudges_before_punt` | 3 | 0 to 10 | After this many small steps that did not get him in range he punches anyway. |
| `nudge_step_s` | 0.9 | 0.3 to 2.5 | Length of one small step closer. Shorter = finer, but a walk covers nothing in its first 0.7 s or so. |
| `walk_aim_in` | 4.0 | 1.5 to 8 | The long walk steps are timed to leave the ball about this far away. Overshoots into the ball: **raise** it. Stops far away: **lower** it. |
| `punt_align_deg` | 12 | 2 to 30 | The ball must be within this many degrees of straight ahead before the punch. Ball goes crooked: **lower**. He turns and turns and never punches: **raise**. |
| `punch_lunge_s` | 0.12 | 0.05 to 0.6 | Seconds the lunge takes. Smaller = harder and faster. |
| `punch_hold_s` | 0.25 | 0 to 1 | Seconds the lunge is held before he comes back. |
| `lost_looks` | 3 | 1 to 8 | Looks in a row without the ball before he starts searching. He searches although the ball is there: **raise** it. |
| `search_walk` | false | true / false | After a full search circle, walk on blind. **Leave false on a desk.** |
| `max_seconds` | 75 | 10 to 600 | The attempt ends, and he rests, after this long. |

**Change a value (from the Mac):**

```bash
g2puntset                           # show the file's path and the value of every setting a run would use now
g2puntset punt_max_in 3.5           # change one value (checked first; a bad value changes nothing)
g2puntset init                      # create the file with every setting at its default (never overwrites)
```

**Or edit it by hand on the Pi:** `ssh "$G2_PI"`, then `nano ~/.local/share/g2/punt_settings.json`, change the number, save. The file is plain JSON (one `"name": value,` per line; keep the commas).
`cd ~/bittleX && PYTHONPATH=. pi_pipeline/.venv/bin/python -m pi_pipeline.behavior.punt_settings` prints what the next run will use and reports any line it did not accept (an unknown name or a value out of range is ignored and reported at the start of the run, never used silently).
**Back to the defaults:** delete the file (`rm ~/.local/share/g2/punt_settings.json`) or set a value back.

**Where the defaults are in the code** (only if you want to change what "default" means): `pi_pipeline/behavior/ball_chase.py`, the constants near the top: `PUNT_MAX_IN`, `NUDGE_MAX_IN`, `NUDGES_BEFORE_PUNT`, `NUDGE_S`, `WALK_AIM_IN`, `PUNT_ALIGN_DEG`, `PUNCH_LUNGE_S`, `PUNCH_HOLD_S`, `LOST_LOOKS`, `SEARCH_WALK`.
The list of settings, their limits and their descriptions is `SPEC` in `pi_pipeline/behavior/punt_settings.py`. The punch's own key poses (the shape of the lunge) are `punch_keys()` in `ball_chase.py`.
After editing code on the Mac: commit, then `g2deploy --once` (below). Do not edit the code on the Pi: the next deploy replaces it.

## 5. Reading an attempt

Each attempt ends with a line like:

```
ATTEMPT: punted at (2.7, 6.7) (in, deg) after 4 looks; walk steps (ball in, seconds): [(13.0, 2.2), (13.0, 2.3)]
```

- `punted at (2.7, 6.7)`: when he punched, the finder read the ball 2.7 in away and 6.7° to the right of straight ahead. **This is the number to tune against**: compare it with how the punch went.
- `walk steps`: for each long walk, how far away the ball was when he started it and how long he walked. If the ball distance is the same before and after a walk, that walk did not move him (known issue: the first walk after a stand-up sometimes covers nothing).
- If the run was started by voice, read it with `ssh "$G2_PI" journalctl -u g2-punt --no-pager -n 60`.

**What we measured so far (2026-10-25):** a ball 2.6 in from the camera threw 18 in straight ahead (claw hits it first); 4.5 to 5 in was just out of reach; 6 to 7 in too far; the first desk attempt punched at 2.7 in. The finder is only accurate to about 1 in at close range.

## 6. A way to dial it in

1. Start at the defaults, ball about 12 in ahead. Run one attempt.
2. Look at the `punted at` distance and what the punch did: did the claw hit the ball first, did it go straight, how far.
3. Change **one** setting (usually `punt_max_in` by 0.5 in) with `g2puntset`, run the next attempt. Keep a note of the setting and the result of each attempt.
4. Once the distance is right, tune the side effects: `punt_align_deg` for crooked punches, `walk_aim_in` for overshooting, `punch_lunge_s` for how hard.
5. For a clean table of distance against result, use `punt_test` (section 2): one punch at each fixed distance, the results in a CSV.

| What you see | Try |
|---|---|
| He punches but the claw misses or barely touches the ball | lower `punt_max_in` |
| He walks into the ball and pushes it before punching | raise `walk_aim_in`; raise `punt_max_in` |
| He punches from far away and the ball does not move | lower `punt_max_in` |
| Right in front of the ball and no punch | the ball is more than `punt_align_deg` off straight (raise it), or the finder lost it; run `--dry-run` and read what it says |
| The ball goes sideways | lower `punt_align_deg`; check he was lined up |
| He searches although the ball is in front of him | raise `lost_looks`; a ball in direct sun goes pale and the finder misses it (shade it or move it) |
| The punch is weak or slow | lower `punch_lunge_s` |
| He turns away from the ball | the ball is out of his view or too far to the side: start it straight ahead |

## 7. If something does not work

- **The board does not answer / G2 goes limp:** check the plug between the Pi and the BiBoard first (it comes undone in falls), then the pack.
- **"G2, punt" does nothing:** the speech recognizer may not have heard the word; run `g2punt` from the Mac instead. The voice service's log: `ssh "$G2_PI" journalctl -u g2-voice -n 40`.
- **After a run the voice service is not back:** `ssh "$G2_PI" sudo systemctl start g2-voice` (or `g2reset`).
- **Pictures:** every picture with the ball found is saved with its box for the future ball detector (`g2pics`, Named: greenball).

## 8. Deploying a code change to the Pi

From the repo root on the Mac, after committing (it ships the last commit):

```bash
g2deploy --once            # deploy now if the Pi answers
g2deploy                   # wait up to 24 h for the Pi, then deploy
bash tools/g2_deploy_when_online.sh --once        # the same, without the alias
```

A deploy restarts the voice service, so it never changes the settings file, and it refuses to run during a walk. The settings file is the only thing you need to change to dial in the punt.
