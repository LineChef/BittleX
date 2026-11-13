# Goals: start a session, answer his suggestions, read what he learned

G2 works toward a goal set by the operator. One spoken command starts a session of up to 10 attempts. After each attempt he scores it with his own camera and IMU, decides on the Pi what to change
for the next attempt (no Claude call), and writes it all down. Code: `pi_pipeline/goals/`.
The first goal is **the ball punt** (the arm fitted, the green treat ball on the floor). A punt is judged by one straight picture about a second after the punch: the ball gone from
in front of the claw, or at least 2 in farther away, counts as punted; still at the claw is a miss. Leave the ball where it rolls: the next attempt looks for it, then searches.

1\. Before a session
-------------------

- The arm is fitted and G2 is on the floor, never a desk (there is no edge detector), with room around him and the ball in sight. Hands near.
- Set the floor label (**"G2, the floor is hardwood"**): what he learns is kept per floor.
- A charged pack: no attempt starts below 30%, and the session reads the pack before every attempt.
- Once, before the first claw look: measure which way the arm pans. Put the ball about 12 in straight ahead, voice service stopped:
  `ssh -t "$G2_PI"`, then `cd ~/bittleX && PYTHONPATH=. pi_pipeline/.venv/bin/python -m pi_pipeline.behavior.claw_look --calibrate`. It saves `claw_pan_sign`.
  `--test` does one look around with the current settings.

2\. Start and stop
-----------------

- Start: **"G2, ball goal"** (also "punt goal", "start the ball goal", "goal attempt")
- Old way: `g2goal run ball_punt --standalone`, or `G2_GOAL_INPROCESS=0` in the Pi's `.env`: the voice service is stopped, the session runs in its own process, the service is started again
- Stop: **"emergency stop"** is not heard during a session (the voice loop is busy running it; the BiBoard's own voice module still hears spoken commands)
- It ends by itself: after 10 attempts, 20 minutes, a pack under 30%, or a fall (with the arm, fall recovery is off: right him by hand)
- A fall after a good punt: the attempt keeps its data: when the ball was punted and seen afterwards with a hit, it is scored as that hit (see below)

- Start: He says "Starting the goal: punt the ball." and the session runs **inside the running voice service** : nothing is stopped or restarted, the serial port to the BiBoard is never closed, and the service's camera and IMU stream are used. Without voice: `g2ball` (same as `g2goal run ball_punt`): it asks the running service to start the goal and follows its log in your terminal
- Old way: It is also the fallback when the service has no camera or serial link. After a stop and restart the BiBoard often went silent to the Pi (no answer to `P`, no IMU frames, the session ended `board_silent`, [`../STATUS.md`](../STATUS.md) open problems 15 and 18)
- Stop: use `g2ballstop` (or `g2goal stop`; he finishes the current move and rests) or `g2stop`. Ctrl-C in the `g2ball` terminal asks the session to stop
- A fall after a good punt: the attempt keeps its data: when the ball was punted and seen afterwards with a hit, it is scored as that hit, noted "then I fell", and counts for what he learns; the session still ends. A fall with no successful punt stays a fall (score 0)


He stands still for 5 s between attempts and rests at the end. Short cues: "target acquired", "searching", "punting", then "Got it." or "Missed."

3\. His suggestions
------------------

Most settings are his to change ("free"). A few belong to the operator: he may only suggest a change ("ask"; today only the lunge speed), and some he never touches ("fixed").
When the voice service comes back after a session, he says each new suggestion, for example *"I have a suggestion from my practice at punt the ball: a lunge time of 0.1 s instead of 0.12 s, because I punched from 3.1 in but the ball only went 4 in. Say confirm, cancel, or review."* No wake word is needed for the answer.

- "confirm" (or "yes"): the change goes into the punt settings file
- "cancel" (or "no"): dropped; he will not suggest that value again for a while
- "review", or nothing: kept for later, in the report and in `g2goal suggestions`; he does not say it again. Later: `g2goal confirm ball_punt punch_lunge_s` or `g2goal cancel ...`

4\. Reading what he learned
--------------------------

```bash
g2goal report                # copy the journal from the Pi and open the report page (ball_punt by default); G2 off: the report from the Mac's copy
g2goal pull                  # copy his goal data to the Mac now (also done every 30 min by g2sync, after every deploy and every g2goal run)
# the review page (g2pics) has a Goals tab: per goal the lessons he saved (flagged when the curation doubts one), what worked for each setting, every attempt, the sessions and turns; a success-since-the-start chart (the rate over every counted attempt, the rate over the last 10, dotted lines where the floor or hardware changed) with a trend tile (the last 10 attempts against the 10 before)
g2goal history ball_punt     # the last sessions as text
g2goal show ball_punt        # every setting: who changes it, its range, the value he uses now, yours if different
g2goal status                # what each goal has learned, per attachment and floor; a change being tried
g2goal reset ball_punt --yes # forget what he learned (the journal keeps the history)
```

**Automatic curation** (`g2goal curate`, runs by itself after every goal session and every pull; `--dry` shows what it would do, `--restore` puts deleted lessons back): attempts made under an older
scoring epoch (`SCORING_EPOCH` in `goals/curate.py`, bumped by any commit that changes how attempts are scored or the ball is seen) are taken out of his records unless they were marked right; a lesson saved to memory
whose attempts were all retracted or retired is deleted (to a 30-day trash); a lesson newer attempts disagree with, or one over 60 days old with nothing newer behind it, is only flagged; the turn log keeps 30 days.
`goal_curation/curation_report.md` says what it did and why. It never touches the goals, overrides or "right" verdicts, the journal, or facts G2 was told.

The Mac keeps a copy in `~/Desktop/G2Memory/goals/` so you can read it while G2 is off: the journal, what he learned, the goals and overrides, the chase and wall
settings, his measured pace, every chase turn and why (`turn_log.jsonl`), every chase decision and why (`decision_log.jsonl`, 50 MB cap, old lines rotated out by the cleanup), the lessons he saved to memory (`lessons.jsonl`), and `history/<date>/` with the copy as it was
before each day's first pull. `pulled_at.txt` says when it was taken. The commands other than `report` and `pull` need G2 on.

The report shows the success rate per session, the settings he uses now against the first session's, the record behind each setting (every value tried, how often it worked,
which way his misses pointed), what he kept and undid, the overrides, each session's attempts,
and the lessons he saved to memory (up to 3 per session, as facts with source `goal_lesson`; he can talk about them). Signs the learning is good: the record for the setting he works on settles on one value, the success rate rises across sessions on
the same floor, the values he keeps hold their record in the next session, the notes match what was seen. A setting flagged "at the end of its range" means a rule may be wrong or the goal is out of reach.
Ten attempts is a small sample: a change kept on 2 or 3 attempts can be luck.

Measured, not judged: his walking pace and turn rates (left and right, long turns and the small alignment pulses) come from the camera, before and after each move, and are kept per
attachment and floor in `~/.local/share/g2/chase_pace.json`. They time every walk and turn, also in a plain "G2, punt". A measured rate replaces the default only after 2 clean samples (`MIN_SAMPLES` in `behavior/chase_pace.py`); until then the defaults time the moves: 28 deg/s for a turn and 24 for a pulse (the firmware turn that is the default gait runs about 28, and lower defaults made every plain turn overshoot). Plain turns and the turn after a claw look stop on the gyro like the line-up turns.

### Editing from the Goals tab

The tab (review page, `g2pics`) also changes things: a goal's size and start phrases, who controls each setting (G2, the operator through his suggestion, the operator only), pins and limits per floor or attachment, undoing or forgetting a learned value, scoring an attempt right or wrong, his lessons (add, rewrite, delete), the order of the goals, new goals and confirming or cancelling his suggestions. Each is the same `g2goal` command described here.

An edit is not sent at once. It waits in `~/Desktop/G2Memory/goals/pending_edits.json` on the Mac, shown in the tab as "pending" with a Cancel, and is sent to the Pi when the Pi is up and no goal session is running: at the start of `g2goal pull`, at the start of `g2goal run`, with `g2goal apply`, or the tab's Apply now button. A newer edit of the same thing replaces the older one. An edit the Pi refuses stays in the list with the reason; what was sent is listed under "Edits sent to G2". A session started by voice ("G2, ball goal") does not send them, so run `g2goal apply` first if you want them in.

5\. Telling him a score was wrong
--------------------------------

Every attempt in the report has a number and a "verdict" column. If the score is wrong (the report says he hit the ball but it was still under the claw, or the finder misread
it), say so from the Mac:

```bash
g2goal verdict ball_punt 7 wrong     # taken out of his records; add --note "under the claw" for a reason, --floor F when two floors have an attempt #7
g2goal verdict ball_punt 8 right     # kept, and counted as agreement
```

The report's "verdicts" tile shows how often the scoring agrees with the operator: that number says how far to trust what he learns.

6\. When he learns something bad
-------------------------------

He keeps a record for every value he tries ("punching from 3 in: 7 of 9 good"), works on one setting at a time, and keeps the value with the best record, so one lucky attempt
cannot set a value. When a value still looks wrong, override it from the Mac:

```bash
g2goal pin ball_punt punt_max_in 3.5             # hold it at the operator's value; he cannot change it (g2goal unpin ball_punt punt_max_in to give it back)
g2goal limit ball_punt punt_max_in 2.5 4.5       # he keeps learning it, only inside the operator's range (unlimit to clear)
g2goal undo ball_punt punt_max_in                # ban his best value for it; he goes to his next best (g2goal unban ball_punt punt_max_in 4.0 to allow it again)
g2goal forget ball_punt punt_max_in              # drop his record for that one setting: back to the settings file's value
g2goal overrides ball_punt                       # list the overrides
```

Add `--floor tile` to any of them for one floor only (the default is everywhere). A pin beats a limit, a limit beats what he learned, and what he learned beats the punt settings
file. Every override is in the report under "Overrides". `g2goal reset ball_punt --yes` still forgets everything a goal learned.

7\. What else teaches him
------------------------

- Plain punts count too: A "G2, punt" or `g2punt` attempt is scored and added to the ball goal's records (shown as "Plain punt" in the report); nothing is changed by it.
- A new floor or new hardware starts from his best elsewhere. His records are kept per attachment, floor and hardware epoch. Under new conditions he starts from his best
  values on the nearest other ones (the same floor on the previous hardware first), with fresh records, so old evidence never holds him at an old answer. **When the hardware changes
  the hardware** (ARM2's wider shoulders and paws, a new servo), add an entry to `pi_pipeline/telemetry/hardware_epochs.json` and deploy; his walking
  pace and turn rates start from the old values the same way.
- A settled setting is left alone: When one value clearly beats the values next to it, he moves on to the next setting his failures point at; it is looked at again if that
  value starts failing.
- The pack % is kept with every attempt (the report's "pack" column); he does not learn from it yet.

8\. Several goals
----------------

- Turn away from walls is a standing goal: always on, never started. Every exploration and every ball chase that meets a wall dials it in, both ways: a bump (or turning but
  still touching) pushes his wall distances out; turning with lots of room to spare, or leaving a ball lying by a wall, pulls them in. Its settings:
  `python -m pi_pipeline.behavior.wall_settings` (the file `~/.local/share/g2/wall_settings.json`); `g2goal report walls` shows what he learned.
- Walls come first: While chasing the ball he never gets closer than `chase_wall_in` (10 in to start, learned, never below 4 in) to a wall, turns away at it, and leaves a ball
  lying nearer a wall than that (the attempt ends "ball by the wall" and does not count against the punt). A bump while walking stops the walk.
- Calibrating the wall reading (`python -m pi_pipeline.vision.wall_distance calibrate`, voice service stopped) is optional: he learns against the reading as it is. After a new
  calibration his records start fresh and his settings carry over to the same real distances, so he adjusts to it on his own.
- The order: `g2goal priority` shows it, `g2goal priority walls ball_punt` sets it (highest first).
- "G2, practise" (or "practice"): he picks what to practise from the stored order, how much he needs it and what he can do right now, says which and why, and starts it (the punt's
  goal session, or a 5-minute exploration roam for walls). "G2, practise walls" or "practise the punt" names one. `g2goal practise` shows his scores without moving him.

8b. The "Identify new objects" goal
-----------------------------------

`g2goal run discover_objects`, or "G2, find new objects" / "G2, object goal". A session is 3 roams of about 3 minutes (10 minutes at most, `minutes` in the goal), in any room and with the head or the arm fitted. G2 explores; whenever something that matches no named object is in view (not a person, not the base of a wall) he takes the picture routine, and the survey pictures are filed under the room he was told he is in (`you're in the kitchen`). Each picture carries a suggested label: the closest object already named in the gallery (the DINOv2 embedder compares each object-like region with the named objects; the gallery is only read), or the camera detector's label when it fired, or "does not know" with the closest name. Nothing is named by him: open `g2pics`, read "G2 thinks: ..." on each picture of the Pictures tab, press Accept or use Name to change it, or answer when he asks "what am I looking at?". A suggestion can only be a name that already has pictures in the gallery, so it improves as more pictures are named.

An attempt is scored from the pictures the roam took: **pictures captured** (success: at least 3 usable survey pictures: sharp enough, sensibly exposed, no person), **few pictures** (1 or 2 usable), **none usable** (pictures taken, none usable), **never found** (no picture stop), fell, or stopped (not counted). The earlier rule needed a new candidate in the gallery, which survey pictures never create (they wait for a label and a promotion), so every roam was scored "nothing new" and the goal showed 0%. He tunes how often he looks for something new (`peek_every_s`), when he stops being picky (`relax_s`, `fallback_s`) and how long a roam is (`roam_s`), per floor and hardware, like the ball goal. "G2, practise" never picks this goal by itself; name it.

It needs an exploration to run: inside the voice service that is `G2_EXPLORE_INPROCESS=1` with the explore, vision and vision_safety features on (not yet tried on G2); when the service is not set up for it, `g2goal run` falls back to the old stop-and-run hand-over (`--standalone`).

What the first run showed: the hand-over run works, with two things to know. The roam skips the speech models (`--light`: no narration, no wake word), because with them loaded the process ran out of memory and sat in swap, never reaching the roam. And the gallery's queue of promoted pictures (`~/.local/share/g2/gallery_pending.json`) is learned at the start of every roam: at about 2 s a picture with the learned embedder, a long queue (349 pictures) held the roam for minutes, so a stale queue is moved aside, not learned again, after a rebuild (`tools/rebuild_gallery.py`). Result of the first run: 0 of 3 (3 to 4 usable pictures each, all of things already known).

Plain exploration feeds the goal too: every exploration of a minute or more is judged like a roam (new candidates, usable pictures) and starts with the goal's learned look settings (peek interval, fallback picture, pickiness; a value set by hand wins). The goal's own roams are not counted twice. When a goal session ends normally (all attempts, the target, the time), the "da naaaa" plays once; not after a fall, a stop, the battery or a silent board.

9\. Where things live on the Pi
------------------------------

- `~/.local/share/g2/goals.json`: changes to a goal (`g2goal set ball_punt --attempts 8 --control punt_max_in=fixed`); missing = the built-in goal
- `~/.local/share/g2/goal_journal.jsonl`: every session, attempt (with its full trace), decision, suggestion answer
- `~/.local/share/g2/goal_state.json`: what he learned, per goal, attachment and floor
- `~/.local/share/g2/punt_settings.json`: the operator's own punt settings: where a goal's first session starts; only a confirmed suggestion writes to it ([`punt.md`](punt.md))
- `~/.local/share/g2/chase_pace.json`: his measured pace and turn rates
- `~/.local/share/g2/goal_overrides.json`: pins, limits and undone values
- `~/.local/share/g2/wall_settings.json`: the operator's own wall settings: where the walls goal starts

Switches: `G2_GOALS`, `G2_GOAL_JOURNAL`, `G2_GOAL_STATE`, `G2_GOAL_OVERRIDES`, `G2_WALL_SETTINGS` and `G2_CHASE_PACE` move the files above; `G2_GOAL_SUGGEST=0` stops the spoken suggestions (they stay in the report).
