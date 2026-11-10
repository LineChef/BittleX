# Goals

G2 works toward a goal the user sets and learns from his attempts, all on the Pi with no API call. How to use it: [`../../docs/guides/goals.md`](../../docs/guides/goals.md).

| Module | What it does |
|---|---|
| `spec.py` | `Knob` (one setting: kind, bounds, step, free / ask / fixed), `Goal` (budget, the user's controls, start phrases), `goals.json`, the built-in `ball_punt` |
| `approach.py` | The `Approach` protocol a goal plugs in (knobs, one attempt, a scorer, a diagnosis table), `AttemptResult`, `Outcome`, the registry |
| `ball_punt.py` | The first approach: one ball-chase attempt (`behavior/ball_chase.py`) and its scorer (hit, missed, never found, pushed away, could not line up, ...) |
| `judge.py` | The shared judgement: a record per setting and value judged by its own stage, failures vote a direction, one setting at a time, the next value by Thompson sampling one step at most, the best-supported value kept; ask knobs become suggestions. A made-up world in the tests checks it finds a known best |
| `overrides.py` | The user's pins, limits and undone values (`g2goal pin / limit / undo / forget`), per scope (everywhere, a floor, an attachment) |
| `journal.py` | `goal_journal.jsonl`, `goal_state.json`, conditions (attachment + floor + hardware epoch) and the nearest other conditions to start from, the lessons saved as memory facts |
| `observe.py` | A plain "G2, punt" attempt scored and added to the ball goal's records; nothing is changed |
| `walls.py` | The "turn away from walls" standing goal: wall encounters scored both ways (bumps push out; turning early or leaving a ball pulls in), in exploration and the chase; its knobs (`behavior/wall_settings.py`); the chase wall check (the reading as it is); settings carried over a new calibration |
| `prior.py` | Where new conditions start: his best values under the nearest other ones (carried over by the approach, e.g. through two wall calibrations) |
| `standing.py` | Standing goals in practice: `apply` their values at the start of an activity, `learn` from its encounters at the end |
| `practice.py` | "G2, practise": each goal's priority x need x can-do-now, the choice and the sentence he says |
| `runner.py` | `GoalSession`: budget, battery before every attempt, attempt, score, judge, record; a fall ends it |
| `suggestions.py` | Says the ask-knob suggestions when the voice service starts; confirm / cancel / review (silence = review) |
| `report.py` | The HTML report and the text history |
| `__main__.py` | `python -m pi_pipeline.goals` (`g2goal`) |

Adding a goal: write an approach (knobs, `run_attempt`, `score`, `diagnosis`), register it, add a `Goal` (built-in or in `goals.json`). The judge, journal, report and voice start are shared.
