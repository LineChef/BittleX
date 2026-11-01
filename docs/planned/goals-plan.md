# Goals plan: G2 works toward a goal you set and learns from his attempts

Agreed with the user 2026-10-31. Backlog item [B28](behavior-ideas.md#b28--goals-g2-works-toward-a-goal-you-set-and-learns-from-his-attempts----built-2026-10-31-not-run-on-g2). It is the first, bounded step of
[B23](behavior-ideas.md#b23--bounded-self-modification-g2-adjusts-its-own-personality-knobs-from-experience) (behaviour that changes from experience) and of
[B24](behavior-ideas.md#b24--agency-g2-forms-its-own-goals-not-just-executes-rule-based-autonomy) (agency). **Built 2026-10-31 (G0 in code, G1 ready), not yet run on G2.** How to use it: [`../guides/goals.md`](../guides/goals.md). State: [`../STATUS.md`](../STATUS.md).

## Decisions (user, 2026-10-31)

- **Learning changes behaviour, at once.** No shadow mode: what G2 learns from one attempt sets how he makes the next one.
- **Only the user sets goals.** G2 chooses how to pursue a goal, never which goal.
- **One spoken command starts a goal session; everything else is automatic.** A session is up to **10 attempts** on G2's own, within its budget. Notes, setting changes and the
  report need no command.
- **The user reads the learning data to judge its quality** (see "Reading the data").
- **Local first.** G2 judges his attempts on the Pi with no API call (see "Local reasoning or a Claude call"). No Claude calls to start; looked at again later if it makes sense.
- **Free is the default** for any setting the user does not name; the free / ask / fixed split below is agreed.
- **The walk is never switched:** G2 always walks with the default gait policy (the attachment's saved gait).
- **Searching:** a claw look (the arm points the camera), turns, back-ups and back-ups with turns are all his to order; the claw look comes first by default.
- **Lining up:** small turns checked with the camera after each one.
- **He measures his own pace and turn rates** from the camera and times his moves with them.
- **Suggestions are said out loud:** the user answers confirm, cancel or review; no answer means review.

## What G2 is free to decide

He never invents a movement and Claude never steers him in real time. He chooses:

1. **the approach**, from a short fixed list per goal;
2. **the settings** of that approach, each with a lowest and highest value set in code;
3. **when to try again, change something, or stop**, inside the session budget.

The safety layers stay underneath and no goal reaches them: emergency stop, the fall guard, the battery gate, the refused moves, the attachment profile, the thermal guard.

### Three kinds of setting (agreed 2026-10-31)

Every setting an approach exposes is marked as one of:

- **free** (the default): G2 changes it on his own, one step at a time, inside its bounds;
- **ask**: G2 may conclude it should change; he says the suggestion when the voice service comes back after the session, and the user answers confirm, cancel or review;
- **fixed**: set by the user or the code, never by G2.

For the ball punt (settings from `behavior/punt_settings.py`, controls in `goals/ball_punt.py` `KNOB_INFO`):

| Kind | Settings | Why |
|---|---|---|
| free | punch distance, small steps closer (from where, how many, how long), where the long walk stops, line-up tolerance, punch hold, looks before searching, the search order, search and scan turn sizes, claw-look pan and lift, one back-up, punts before backing up, what to do when the ball vanishes up close, the alignment pulse, alignment tries, what to do when he cannot line up | Where and when he punches, how he lines up, looks and searches: the outcome measures them directly |
| ask | `punch_lunge_s` | A faster lunge hits harder but is the move most likely to tip him on the arm payload |
| fixed | `search_walk`, `max_seconds`, `back_up_budget_s`, `claw_pan_sign`, the budget, the success definition, battery limits | Walking blind and backing up are only safe on a big floor (no edge detector); the pan direction is measured, not learned; the rest define the goal |

**Not a setting at all: the walk.** Always the default gait policy (user, 2026-10-31). One gait keeps the learning clean: every change he makes is judged against the same walk,
so a better score means the setting helped and not that the gait changed underneath; his measured pace stays one number per floor instead of two; it is the policy trained for
this payload; and it keeps to the rule against comparing gaits on G2.

**Measured, not judged** (`behavior/chase_pace.py`): his walking pace and his turn rates (left and right, long turns and short alignment pulses), from the ball's distance and
bearing before and after each move, per attachment and floor. They time each walk and turn. A move counts only when both readings are clean (the ball whole in the picture, it moved
the right way), so a pushed ball or a misread is left out.

Beyond settings he chooses the approach (once a goal has more than one), and per session when to rest between attempts (thermal guard, pack %) and when to stop early
because the last attempts all succeeded with nothing left to try.

## The parts

| Part | What |
|---|---|
| **Goal** | A JSON entry on the Pi (`~/.local/share/g2/goals.json`, written with `g2goal set`): what success means as measured by his own sensors, the allowed approaches, the settings he may change with their bounds, the budget (attempts, minutes, lowest pack %, falls) |
| **Approach** | An existing behaviour run with given settings. The first one is the ball chase (`behavior/ball_chase.py`), whose settings and bounds already exist in `behavior/punt_settings.py` |
| **Attempt record** | One line per attempt in `~/.local/share/g2/goal_journal.jsonl`: the settings used, the conditions (floor label, pack %, attachment, policy), the measured outcome, why it ended |
| **Judgement** | After each attempt, local code reads the outcome, decides what to change for the next attempt and writes why, citing the attempts it used |
| **Learned settings** | `~/.local/share/g2/goal_state.json`: the best known settings per goal and conditions (attachment + floor), the starting point of the next session. The user's own `punt_settings.json` is the starting point of the first session and is never overwritten |
| **Notes** | Each decision carries a one-line first-person note built from the numbers. At the end of a session up to 3 of them are kept as memory facts (source `goal_lesson`, importance 2, never core), so he can talk about them when asked |
| **Suggestions** | For ask settings: said when the voice service starts after the session; "confirm" writes it into the user's own settings, "cancel" drops it (not suggested again for 30 attempts), "review" or silence keeps it in the report (`g2goal confirm` / `cancel` later) |

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

1. **Diagnosis: a table from a measured failure to the setting it points at.** Every attempt ends with an outcome code and its numbers. For the ball punt, for example:

   | Outcome | Measured | Next attempt, in order (the first one that can still change) |
   |---|---|---|
   | `hit` / `hit_unseen` | the ball moved 8 in or more / went out of sight | keep everything |
   | `missed` | the ball moved under 3 in | punch from closer, line up tighter, more small steps |
   | `missed_off_line` | ... and the punch was well off straight | line up tighter, more alignment turns |
   | `missed_vanished` | punched at a ball out of sight at the claw, it did not move | the other `when_vanished`, punch from closer |
   | `weak_hit` | 3 to 8 in | punch from closer, line up tighter; suggest a faster lunge (ask) |
   | `pushed_away` | the ball farther right after a walk toward it | stop the walk farther out, shorter small steps |
   | `never_reached` | saw it, never got within 7 in | stop the walk closer, small steps from farther out |
   | `align_overshoot` / `align_no_move` / `align_stuck` | small turns swung past the ball / did not move him / never lined up | shorter pulses / longer pulses / more tries, the other `when_misaligned` |
   | `never_punted` | got close, never punched | line-up tolerance wider, fewer small steps, punch from farther |
   | `never_found` | never saw the ball | another search order, a higher or wider claw look, smaller scan turns, fewer looks before searching |
   | `fell` | | undo the change being tried; the session ends |

   The table is data (`DIAGNOSIS` in `goals/ball_punt.py`); the scores are 0 to 1, a hit higher the farther the ball went and the sooner it happened.

2. **Evidence: a change is kept only if it helps.** One setting changes at a time, by one step. A change is judged over the next 2 to 3 attempts against the attempts before it.
   If the score is no better it is undone and logged ("tried punching from 3.5 in: 1 of 3, back to 4 in"). One attempt is never enough to judge a change, except a fall, which
   marks the setting in use as suspect. Results are counted per attachment and floor, so what works on hardwood is not carried to tile.

Ten attempts a session is a small sample. The judgement is deliberately slow (one step at a time, several attempts per verdict), and the report shows how many attempts back each
conclusion, so a lucky streak reads as a lucky streak.

## Local reasoning or a Claude call

| | Local on the Pi | A Claude call |
|---|---|---|
| Cost | free | billed per call (the API rule: sparingly) |
| Speed | instant, so the next attempt can use it | seconds plus network; one call between every two attempts would add up fast |
| Counting and comparing ("4 of 5 from 3.5 in, 1 of 4 from 4.5 in") | exact | can misread numbers |
| Notes true to the data | always: built from the numbers | can sound confident about a cause that 10 attempts do not support |
| Testable and repeatable | yes, same input gives the same choice | no |
| A pattern nobody wrote a rule for ("the first walk after a stand-up covers nothing") | cannot see it | can, from the event log |
| A new idea to try (a settle step, a new approach) | cannot | can suggest it, but G2 can only use what is in his list, so it becomes a code change anyway |

**Recommendation:** G2 does all the judging locally; that is what makes the next attempt different. Claude's real value is spotting patterns and proposing new approaches or
settings, which needs a code change to act on. That review happens when the user and Claude Code read the report together, at no cost on the Pi. An optional end-of-session Claude
call (one per session, through `MemoryCallGate`) can be added later if the reviews show patterns the local rules keep missing. It is not part of the first build.

## Reading the data

- **The journal** (`goal_journal.jsonl` on the Pi) holds everything: attempts, outcomes, every decision with its "because" and the attempt numbers behind it, the notes.
- **`g2goal pull`** copies it to the Mac (like `g2pics pull`).
- **`python -m pi_pipeline.goals report --html out.html`** builds one page per goal:
  - the latest session: one row per attempt (settings, outcome, numbers), and the decisions between them;
  - the learning curve: success rate per session and each setting's value over time;
  - each note with the evidence behind it, so it can be judged as right, wrong or too early.

  Claude Code can publish it as a private page to read on the phone. The verdicts can be kept on that page later if they turn out to be worth feeding back.
- **`python -m pi_pipeline.diag report`** gets a goal section, so a session's walks, camera faults and falls sit next to its attempts.
- **`g2goal history` / `g2goal explain`** on the Pi: the same data as text. `g2goal reset GOAL` throws away what a goal has learned (the journal is kept).

What to look for when judging the learning: does the success rate rise across sessions on the same floor; do the kept changes keep their gains in the next session; do the
notes match what you saw; is any setting drifting to one end of its bounds (a sign the rule is wrong, or the goal is out of reach).

## Adding a goal later

The framework knows nothing about balls. A goal is three pieces, each found by name in a registry (like `personality/traits.py`'s `REGISTRY`):

| Piece | What it provides |
|---|---|
| **Approach** | `settings()`: each setting with its kind (free / ask / fixed), type, bounds, step and default; `run(settings, ctx) -> AttemptResult` (events plus measured numbers) |
| **Scorer** | `score(result) -> Outcome`: an outcome code, a graded score from 0 to 1 (not only hit or miss: "the ball moved 9 in" carries more to learn from than "hit") and the numbers |
| **Diagnosis table** | Data, not code: outcome code -> the settings it points at and which way |

Everything else is shared by every goal: the session loop and budget, the keep-or-undo judge, choosing between approaches, counting per conditions, the journal, notes,
memory facts and the report. The conditions a result is counted under are the shared ones (attachment, floor) plus any the goal adds (a room once place memory names rooms,
the light level). A goal can later be made of steps (find the ball, then punt it toward a spot), each step its own goal with its own scorer.

Goals that fit later, with what is needed first:

| Goal | Scored by | Needs first |
|---|---|---|
| Explore N minutes without a fall or bump | the exploration recap | nothing |
| Find a named object | recognition at a survey stop | recognition checked on G2 |
| Punt the ball toward a spot | where the ball ends up in the picture | the ball punt goal working |
| Go to a room | the room vote | place memory P2 to P4 |
| Walk straight across a floor | heading drift from the walk log | the user's call: tuning the walk on G2 touches the gait-comparison rule |

## Code layout

`pi_pipeline/goals/` (module list: [`../../pi_pipeline/goals/README.md`](../../pi_pipeline/goals/README.md)), with the ball chase's search, claw look, alignment and measured pace in `behavior/ball_chase.py`, `behavior/claw_look.py` and `behavior/chase_pace.py`, and the voice hand-over in `goal_launch.py`. Same pattern as the rest of `pi_pipeline`: pure logic with injected I/O, tested on a dev machine against fakes and synthetic pictures (`tests/test_goals.py`).

## Phases and gates

| Phase | What | Gate |
|---|---|---|
| **G0** | Goal format, scorers, judge, journal, report, spoken suggestions; tested against fakes and synthetic pictures | Built 2026-10-31, tests pass |
| **G1** | The ball-punt goal live on G2: start phrase, 10 attempts, judging between attempts (no shadow mode), notes, report | The scorer agrees with the user's call on the attempts; no unsafe behaviour. The next hardware run |
| **G2** | A second goal (exploring N minutes without a fall or a bump, scored from the recap) | Not yet (user, 2026-10-31) |
| **G3** | Optional end-of-session Claude review, if the reports show patterns the rules miss | Its notes beat the local ones in the user's reading, worth the cost |
| **G4** | Several goals, G2 picks which to pursue (B24) | A later decision by the user |
