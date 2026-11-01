"""Goals (docs/planned/goals-plan.md, B28): G2 works toward a goal the user sets and learns from his attempts.

The user sets a goal and starts a session with one spoken command; G2 makes up to the goal's number of attempts on his own. After each attempt he scores it with his own sensors,
judges it on the Pi (no API call) and changes how he makes the next one. Everything is written to a journal the user reads as a report.

  spec.py       Knob (one setting an approach exposes: bounds, step, free / ask / fixed), Goal (budget, controls), goals.json
  approach.py   the Approach protocol, AttemptResult, Outcome, the registry of approaches by name
  ball_punt.py  the first approach: the ball chase (behavior/ball_chase.py) as one attempt = find the ball, walk up, punt it once
  judge.py      the shared judgement: a measured failure -> the setting it points at (the approach's diagnosis table), one change at a time, kept only if it helps
  journal.py    goal_journal.jsonl (sessions, attempts, decisions, notes) and goal_state.json (what each goal has learned, per attachment and floor)
  runner.py     GoalSession: budget -> settings -> attempt -> score -> judge -> record
  report.py     the HTML report the user reads to judge the learning
  __main__.py   `python -m pi_pipeline.goals` (g2goal): list | show | set | run | status | history | reset | report

Nothing in this package reaches a safety layer: emergency stop, the fall guard, the battery gate, refused moves and the attachment profile stay underneath every approach.
"""
