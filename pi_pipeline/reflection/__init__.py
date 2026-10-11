"""Reflection (docs/plan-detail/reflection-plan.md): G2 looks back on what happened to him.

  recap.py     level 1: a plain recap of each exploration session, counted from his own logs (no API call), kept in `experiences.jsonl`
  reflect.py   level 2: one Claude call over the latest recaps writes up to three short notes about his own experience (dry run by default)
  Level 3 is local too: "what did you do?" and "what have you learned?" are answered from the recaps and the notes (voice/commands.py, voice/loop.py).
"""
