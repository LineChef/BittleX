# Goals plan: G2 works toward a goal you set and learns from his attempts

Agreed with the user 2026-10-31. Backlog item [B28](behavior-ideas.md#b28--goals-g2-works-toward-a-goal-you-set-and-learns-from-his-attempts----built-2026-10-31-not-run-on-g2). It is the first, bounded step of
[B23](behavior-ideas.md#b23--bounded-self-modification-g2-adjusts-its-own-personality-knobs-from-experience) (behaviour that changes from experience) and of
[B24](behavior-ideas.md#b24--agency-g2-forms-its-own-goals-not-just-executes-rule-based-autonomy) (agency). **Built 2026-10-31 (G0 in code, G1 ready), not yet run on G2.** How to use it: [`../guides/goals.md`](../guides/goals.md). State: [`../STATUS.md`](../STATUS.md).

## Decisions (user, 2026-10-31)

- Learning changes behaviour, at once: No shadow mode: what G2 learns from one attempt sets how he makes the next one.
- Only the user sets goals: G2 chooses how to pursue a goal, never which goal.
- One spoken command starts a goal session; everything else is automatic. A session is up to **10 attempts** on G2's own, within its budget. Notes, setting changes and the
  report need no command.
- The user reads the learning data to judge its quality (see "Reading the data").
- Local first: G2 judges his attempts on the Pi with no API call (see "Local reasoning or a Claude call"). No Claude calls to start; looked at again later if it makes sense.
- Free is the default for any setting the user does not name; the free / ask / fixed split below is agreed.
- The walk is the default gait policy (the attachment's saved gait) for everything except the dialing-in steps close to the ball, which use Petoi's scripted walk (`nudge_gait`, a fixed setting G2 never changes; user, 2026-11-04). The long walk is never switched.
- Searching: a claw look (the arm points the camera), turns, back-ups and back-ups with turns are all his to order; the claw look comes first by default.
- Lining up: small turns checked with the camera after each one.
- He measures his own pace and turn rates from the camera and times his moves with them.
- Suggestions are said out loud: the user answers confirm, cancel or review; no answer means review.

## What G2 is free to decide

He never invents a movement and Claude never steers him in real time. He chooses:

1. the approach, from a short fixed list per goal;
2. the settings of that approach, each with a lowest and highest value set in code;
3. when to try again, change something, or stop, inside the session budget.

The safety layers stay underneath and no goal reaches them: emergency stop, the fall guard, the battery gate, the refused moves, the attachment profile, the thermal guard.

### Three kinds of setting (agreed 2026-10-31)

Every setting an approach exposes is marked as one of:

- free (the default): G2 changes it on his own, one step at a time, inside its bounds;
- ask: G2 may conclude it should change; he says the suggestion when the voice service comes back after the session, and the user answers confirm, cancel or review;
- fixed: set by the user or the code, never by G2.

For the ball punt (settings from `behavior/punt_settings.py`, controls in `goals/ball_punt.py` `KNOB_INFO`):

- free: Settings: punch distance, small steps closer (from where, how many, how long), where the long walk stops, line-up tolerance, looks before searching, the search order, the turn between claw looks, claw-look pan and lift, what to do when the ball vanishes up close, the alignment pulse, alignment tries, what to do when he cannot line up; Why: Where and when he punches, how he lines up, looks and searches: the outcome measures them directly, and every free setting is named by at least one outcome (a test checks it)
- ask: Settings: `punch_lunge_s`; Why: A faster lunge hits harder but is the move most likely to tip him on the arm payload
- fixed: Settings: `search_walk`, `max_seconds`, `back_up_budget_s`, `claw_pan_sign`, the budget, the success definition, battery limits; Why: Walking blind and backing up are only safe on a big floor (no edge detector); the pan direction is measured, not learned; the rest define the goal
- fixed: Settings: `punch_hold_s`, `back_up_s`, `stuck_punts`, `search_step_deg`; Why: No outcome points at them, so G2 could never change them anyway (user, 2026-10-31); they become free again only with an outcome that names them

**Not a setting at all: the walk.** Always the default gait policy (user, 2026-10-31). One gait keeps the learning clean: every change he makes is judged against the same walk,
so a better score means the setting helped and not that the gait changed underneath; his measured pace stays one number per floor instead of two; it is the policy trained for
this payload; and it keeps to the rule against comparing gaits on G2.

**Measured, not judged** (`behavior/chase_pace.py`): his walking pace and his turn rates (left and right, long turns and short alignment pulses), from the ball's distance and
bearing before and after each move, per attachment and floor. They time each walk and turn. A move counts only when both readings are clean (the ball whole in the picture, it moved
the right way), so a pushed ball or a misread is left out.

Beyond settings he chooses the approach (once a goal has more than one), and per session when to rest between attempts (thermal guard, pack %) and when to stop early
because the last attempts all succeeded with nothing left to try.

## The parts

- Goal: A JSON entry on the Pi (`~/.local/share/g2/goals.json`, written with `g2goal set`): what success means as measured by his own sensors, the allowed approaches, the settings he may change with their bounds, the budget (attempts, minutes, lowest pack %, falls)
- Approach: An existing behaviour run with given settings. The first one is the ball chase (`behavior/ball_chase.py`), whose settings and bounds already exist in `behavior/punt_settings.py`
- Attempt record: One line per attempt in `~/.local/share/g2/goal_journal.jsonl`: the settings used, the conditions (floor label, pack %, attachment, policy), the measured outcome, why it ended
- Judgement: After each attempt, local code reads the outcome, decides what to change for the next attempt and writes why, citing the attempts it used
- Learned settings: `~/.local/share/g2/goal_state.json`: the best known settings per goal and conditions (attachment + floor), the starting point of the next session. The user's own `punt_settings.json` is the starting point of the first session and is never overwritten
- Notes: Each decision carries a one-line first-person note built from the numbers. At the end of a session up to 3 of them are kept as memory facts (source `goal_lesson`, importance 2, never core), so he can talk about them when asked
- Suggestions: For ask settings: said when the voice service starts after the session; "confirm" writes it into the user's own settings, "cancel" drops it (not suggested again for 30 attempts), "review" or silence keeps it in the report (`g2goal confirm` / `cancel` later)

### Session flow

1. The user says the goal's start phrase. The voice service hands over to the goal session (the same systemd hand-over as `punt_launch.py`) and always starts again after.
2. Before each attempt: read the pack % (`power.battery.motion_gate`; with the voice service stopped there is no battery watch), check the budget, load the settings the
   last judgement chose.
3. Run the attempt; measure its outcome.
4. Judge it, write the decision and its note, set the next attempt's settings.
5. The session ends after 10 attempts, at the goal's success target, at the budget, on low battery, on "stop", or on a fall (with the arm, fall recovery is off: a fall always ends the
   session). He rests at the end. The session's notes are saved and the report is written.
6. The voice service starts again and says any new suggestion (ask settings); the user answers confirm, cancel or review (silence = review).

## How G2 judges an attempt (local)

Two layers, both plain code with tests:

1. Diagnosis: a table from a measured failure to the setting it points at. Every attempt ends with an outcome code and its numbers. For the ball punt, for example:

   - `hit` / `hit_unseen`: Measured: the ball moved 8 in or more / went out of sight; The settings it points at and which way (the first one gets the most weight toward the focus): keep everything
   - `missed`: Measured: the ball moved under 3 in; The settings it points at and which way (the first one gets the most weight toward the focus): punch from closer, line up tighter, more small steps
   - `missed_off_line`: Measured: ... and the punch was well off straight; The settings it points at and which way (the first one gets the most weight toward the focus): line up tighter, more alignment turns
   - `missed_vanished`: Measured: punched at a ball out of sight at the claw, it did not move; The settings it points at and which way (the first one gets the most weight toward the focus): the other `when_vanished`, punch from closer
   - `weak_hit`: Measured: 3 to 8 in; The settings it points at and which way (the first one gets the most weight toward the focus): punch from closer, line up tighter; suggest a faster lunge (ask)
   - `pushed_away`: Measured: the ball farther right after a walk toward it; The settings it points at and which way (the first one gets the most weight toward the focus): stop the walk farther out, shorter small steps
   - `never_reached`: Measured: saw it, never got within 7 in; The settings it points at and which way (the first one gets the most weight toward the focus): stop the walk closer, small steps from farther out
   - `align_overshoot` / `align_no_move` / `align_stuck`: Measured: small turns swung past the ball / did not move him / never lined up; The settings it points at and which way (the first one gets the most weight toward the focus): shorter pulses / longer pulses / more tries, the other `when_misaligned`
   - `never_punted`: Measured: got close, never punched; The settings it points at and which way (the first one gets the most weight toward the focus): line-up tolerance wider, fewer small steps, punch from farther
   - `never_found`: Measured: never saw the ball; The settings it points at and which way (the first one gets the most weight toward the focus): another search order, a higher or wider claw look, smaller scan turns, fewer looks before searching
   - `fell`: The settings it points at and which way (the first one gets the most weight toward the focus): undo the change being tried; the session ends

   The table is data (`DIAGNOSIS` in `goals/ball_punt.py`); the scores are 0 to 1, a hit higher the farther the ball went and the sooner it happened.

2. Evidence: every attempt counts: (rebuilt 2026-10-31). The first version judged a change on 2 or 3 attempts against the 3 before it and then banned the step it undid; in a
   made-up world with a known best value (hit chance peaking at punching from 3 in, starting at 4 in, 2,000 runs) it ended within one step of the best only 14% of the time after
   30 attempts: it got stuck, not random. The judge now:
   - keeps a record per setting and value (attempts, hits, score), per attachment and floor, across sessions;
   - judges each setting by its own stage: search settings by how fast he found the ball, walking-up settings by whether he got close without pushing it, lining-up settings
     by whether he punched lined up, punch settings only on attempts that punched (`STAGE_OF` in `goals/ball_punt.py`);
   - counts each failure as a vote for a direction at the value in use ("missed" votes for punching from closer);
   - works on one setting at a time, the one recent failures point at most (the focus); the others stay at their best-supported value;
   - picks the focus setting's next value among the current one and the neighbour the votes point to, by drawing a hit rate from each one's record (Thompson sampling): a value
     with a good record is chosen most often, an untried neighbour still gets a chance, and a move is never more than one step;
   - keeps, and starts the next session from, the value with the best record over at least 2 attempts, not the last one tried;
   - bans a value he fell trying for 30 attempts.

   - leaves a setting alone once it has settled (its best value has 5 attempts and every neighbour 3, all clearly worse) and moves on to the next one; looks again if that
     value starts failing;
   - keys the records by attachment, floor and **hardware epoch** (`telemetry/hardware_epochs.json`); new conditions start from his best values under the nearest other ones,
     with fresh records (tested: after a hardware change that moves the best value, keeping the old records left him at the old answer in 90% of runs; starting fresh from
     the old best reached the new one in 68%);
   - counts plain "G2, punt" attempts in the records without changing anything (`goals/observe.py`);
   - takes out an attempt the user marks wrong (`g2goal verdict GOAL N wrong`); the share of agreeing verdicts says how far to trust the scorer;
   - keeps the pack % with every attempt (not learned from yet: 10 attempts a session is too little data for it).

   In the same made-up world it ends within one step of the best in 90% of runs after 30 attempts (95% after 60); in a noisier one (60% peak, 25% misread misses) 62% after 30
   and 77% after 60. A copy of that world is a permanent test (`tests/test_goals.py`: at least 85% within one step after 30 attempts). Expect about 3 sessions per setting to
   settle on a real floor, which is noisier than the made-up world.

The report shows each value's record ("3 in: 7 of 9 good"), so a value backed by evidence and one still settling look different.

## Overrides: when he learns something bad

All from the Mac (`g2goal`, `goals/overrides.py`, `~/.local/share/g2/goal_overrides.json`); `--floor tile` or `--scope attachment=arm|floor=tile` narrows one, the default is
every attachment and floor. Who wins: a pin > a limit > what he learned > the user's own settings file.

- `pin GOAL KNOB VALUE` / `unpin`: holds a setting at the user's value; he cannot change it
- `limit GOAL KNOB LO HI` / `unlimit`: he keeps learning it, only inside the user's range
- `undo GOAL KNOB` / `unban GOAL KNOB VALUE`: bans his best value for it (for good, until unbanned); he goes to his next best
- `forget GOAL KNOB`: drops his record for one setting: back to the user's value, he may learn it again
- `overrides GOAL`: lists them

Every override goes into the journal and the report ("Your overrides").

## Several goals: which one, and when (user-approved 2026-10-31, built the same day)

Goals come in two kinds (`kind` in `goals/spec.py`):

- Shape: Task (punt the ball): starts, succeeds or fails, ends; Standing (turn away from walls): always on, no start or end
- An attempt: Task (punt the ball): one find, walk and punch; Standing (turn away from walls): every wall encounter, in any activity
- Chosen?: Task (punt the ball): yes, one at a time; Standing (turn away from walls): never: it runs inside every task as a limit

**The walls goal** (`goals/walls.py`, its settings in `behavior/wall_settings.py`, `~/.local/share/g2/wall_settings.json`): every attempt that meets a wall dials it in, in
both directions (user, 2026-10-31). Every exploration and every ball chase hands it its wall encounters (`goals/standing.py`):

- Exploring: Good: turned away, no touch in the next 8 s; Too careful (pulls him closer): turned away with the wall still more than 12 in off; Too late (pushes him farther): turned but still touched it; bumped with no turn (the hit sequence or the IMU contact)
- Chasing: Good: turned away at `chase_wall_in`, no touch; Too careful (pulls him closer): left a ball lying by a wall; Too late (pushes him farther): turned but still touched it; bumped while walking (the policy walk's IMU contact, which also stops the walk)

He tunes the exploration's turn distance (`wall_turn_in`, the wall reading's `TURN_IN`), its single-look distance, the fast-look distance, how short walks stop before a wall, his
turn, and how close the chase may get (`chase_wall_in`, never below 4 in). Each is judged only by encounters where it acts. A made-up-world test checks that `chase_wall_in` settles
between bumps and left balls from either side.

**The wall reading is used as it is, calibrated or not** (user, 2026-10-31): he learns the distances in the reading's own inches, so a consistent error cancels out; calibrating
still helps by cutting noise. **A new calibration** is a new condition (its time is part of the walls goal's conditions): his records start fresh, and his settings start from the
old ones carried through both calibrations to the same picture rows (`translate_prior`), so he turns at the same real distance and re-tunes from there.

**How he decides, highest first:**

1. Safety: emergency stop, the fall guard, the battery limit.
2. The user's command: a goal's start phrase runs that task.
3. Standing goals limit every task, in the priority order (`g2goal priority`, default walls above the punt: user, 2026-10-31). While chasing he never walks closer than
   `chase_wall_in` (10 in) to a wall, turns away when he is that close, and leaves a ball lying nearer a wall than that alone (the attempt ends "ball by the wall" and is not
   counted against the punt). With no wall calibration at all the chase runs without the check and says so.
4. "G2, practise": he picks a task or standing goal by your priority x his need (a low recent success rate, few attempts here, days since he practised it, minus settled
   settings) x whether it can be done now (the attachment it needs; for the punt, the ball in the camera's picture right now). He says which and why ("I'll practise punt the
   ball: 3 of 8 good here lately, and I can see the ball"); "G2, practise walls" names one. A task starts its goal session; walls start an exploration roam of 5 minutes.
5. Not built, the user's later decision (B24): practising without being asked.

## Local reasoning or a Claude call

- Cost: Local on the Pi: free; A Claude call: billed per call (the API rule: sparingly)
- Speed: Local on the Pi: instant, so the next attempt can use it; A Claude call: seconds plus network; one call between every two attempts would add up fast
- Counting and comparing ("4 of 5 from 3.5 in, 1 of 4 from 4.5 in"): Local on the Pi: exact; A Claude call: can misread numbers
- Notes true to the data: Local on the Pi: always: built from the numbers; A Claude call: can sound confident about a cause that 10 attempts do not support
- Testable and repeatable: Local on the Pi: yes, same input gives the same choice; A Claude call: no
- A pattern nobody wrote a rule for ("the first walk after a stand-up covers nothing"): Local on the Pi: cannot see it; A Claude call: can, from the event log
- A new idea to try (a settle step, a new approach): Local on the Pi: cannot; A Claude call: can suggest it, but G2 can only use what is in his list, so it becomes a code change anyway

Recommendation: G2 does all the judging locally; that is what makes the next attempt different. Claude's real value is spotting patterns and proposing new approaches or
settings, which needs a code change to act on. That review happens when the user and Claude Code read the report together, at no cost on the Pi. An optional end-of-session Claude
call (one per session, through `MemoryCallGate`) can be added later if the reviews show patterns the local rules keep missing. It is not part of the first build.

## Reading the data

- The journal (`goal_journal.jsonl` on the Pi) holds everything: attempts, outcomes, every decision with its "because" and the attempt numbers behind it, the notes.
- `g2goal pull`: copies it to the Mac (like `g2pics pull`).
- `python -m pi_pipeline.goals report --html out.html`: builds one page per goal:
  - the latest session: one row per attempt (settings, outcome, numbers), and the decisions between them;
  - the learning curve: success rate per session and each setting's value over time;
  - each note with the evidence behind it, so it can be judged as right, wrong or too early.

  Claude Code can publish it as a private page to read on the phone. The verdicts can be kept on that page later if they turn out to be worth feeding back.
- `python -m pi_pipeline.diag report`: gets a goal section, so a session's walks, camera faults and falls sit next to its attempts.
- `g2goal history` / `g2goal explain` on the Pi: the same data as text. `g2goal reset GOAL` throws away what a goal has learned (the journal is kept).

What to look for when judging the learning: does the success rate rise across sessions on the same floor; do the values he keeps hold their record in the next session; is the record for the setting he works on growing toward one value; do the
notes match what you saw; is any setting drifting to one end of its bounds (a sign the rule is wrong, or the goal is out of reach).

## Adding a goal later

The framework knows nothing about balls. A goal is three pieces, each found by name in a registry (like `personality/traits.py`'s `REGISTRY`):

- Approach: `settings()`: each setting with its kind (free / ask / fixed), type, bounds, step and default; `run(settings, ctx) -> AttemptResult` (events plus measured numbers)
- Scorer: `score(result) -> Outcome`: an outcome code, a graded score from 0 to 1 (not only hit or miss: "the ball moved 9 in" carries more to learn from than "hit") and the numbers
- Diagnosis table: Data, not code: outcome code -> the settings it points at and which way

Everything else is shared by every goal: the session loop and budget, the judge (records, direction votes, the focus setting, Thompson sampling), the user's overrides, choosing between approaches, counting per conditions, the journal, notes,
memory facts and the report. The conditions a result is counted under are the shared ones (attachment, floor) plus any the goal adds (a room once place memory names rooms,
the light level). A goal can later be made of steps (find the ball, then punt it toward a spot), each step its own goal with its own scorer.

Goals that fit later, with what is needed first:

- Explore N minutes without a fall or bump: Scored by: the exploration recap; Needs first: nothing
- Find a named object: Scored by: recognition at a survey stop; Needs first: recognition checked on G2
- Punt the ball toward a spot: Scored by: where the ball ends up in the picture; Needs first: the ball punt goal working
- Go to a room: Scored by: the room vote; Needs first: place memory P2 to P4
- Walk straight across a floor: Scored by: heading drift from the walk log; Needs first: the user's call: tuning the walk on G2 touches the gait-comparison rule

## Code layout

`pi_pipeline/goals/` (module list: [`../../pi_pipeline/goals/README.md`](../../pi_pipeline/goals/README.md)), with the ball chase's search, claw look, alignment and measured pace in `behavior/ball_chase.py`, `behavior/claw_look.py` and `behavior/chase_pace.py`, and the voice hand-over in `goal_launch.py`. Same pattern as the rest of `pi_pipeline`: pure logic with injected I/O, tested on a dev machine against fakes and synthetic pictures (`tests/test_goals.py`).

## Phases and gates

- G0: What: Goal format, scorers, judge, journal, report, spoken suggestions; tested against fakes and synthetic pictures; Gate: Built 2026-10-31, tests pass
- G1: What: The ball-punt goal live on G2: start phrase, 10 attempts, judging between attempts (no shadow mode), notes, report; Gate: The scorer agrees with the user's call on the attempts; no unsafe behaviour. The next hardware run
- G2: What: Several goals: task and standing kinds, the walls goal (learned both ways in exploration and the chase, carried over a new calibration), the priority order, "G2, practise"; Gate: Built 2026-10-31
- G3: What: Optional end-of-session Claude review, if the reports show patterns the rules miss; Gate: Its notes beat the local ones in the user's reading, worth the cost
- G4: What: Several goals, G2 picks which to pursue (B24); Gate: A later decision by the user
