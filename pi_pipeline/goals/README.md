# Goals

G2 works toward a goal the user sets and learns from his attempts, all on the Pi with no API call. How to use it: [`../../docs/guides/goals.md`](../../docs/guides/goals.md).
Design and decisions: [`../../docs/planned/goals-plan.md`](../../docs/planned/goals-plan.md).

| Module | What it does |
|---|---|
| `spec.py` | `Knob` (one setting: kind, bounds, step, free / ask / fixed), `Goal` (budget, the user's controls, start phrases), `goals.json`, the built-in `ball_punt` |
| `approach.py` | The `Approach` protocol a goal plugs in (knobs, one attempt, a scorer, a diagnosis table), `AttemptResult`, `Outcome`, the registry |
| `ball_punt.py` | The first approach: one ball-chase attempt (`behavior/ball_chase.py`) and its scorer (hit, missed, never found, pushed away, could not line up, ...) |
| `judge.py` | The shared judgement: a failure points at a knob (the diagnosis table), one step at a time, kept only if the next attempts score better; ask knobs become suggestions |
| `journal.py` | `goal_journal.jsonl`, `goal_state.json`, conditions (attachment + floor), the lessons saved as memory facts |
| `runner.py` | `GoalSession`: budget, battery before every attempt, attempt, score, judge, record; a fall ends it |
| `suggestions.py` | Says the ask-knob suggestions when the voice service starts; confirm / cancel / review (silence = review) |
| `report.py` | The HTML report and the text history |
| `__main__.py` | `python -m pi_pipeline.goals` (`g2goal`) |

Adding a goal: write an approach (knobs, `run_attempt`, `score`, `diagnosis`), register it, add a `Goal` (built-in or in `goals.json`). The judge, journal, report and voice start are shared.
