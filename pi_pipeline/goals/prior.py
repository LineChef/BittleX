"""Where new conditions start (a new floor, new hardware, a new wall calibration): his best values under the nearest other conditions of the same goal, with fresh records.

`journal.prior_conditions` orders the candidates (the same floor on earlier hardware first). An approach may carry the values over to the new conditions (`translate_prior`:
the walls goal maps its distances through the old and new wall calibrations, so he turns at the same real distance).
"""
from __future__ import annotations

import copy


def find_prior(goal, approach, knobs, state, cond: dict, base: dict, overrides: dict | None = None) -> tuple[dict | None, str | None]:
    """(values, the conditions key they came from) or (None, None)."""
    from .journal import prior_conditions
    from .judge import Judge
    goal_state = state.data.get(goal.id) or {}
    for key in prior_conditions(goal_state, cond):
        other = Judge(knobs, approach.diagnosis, copy.deepcopy(goal_state[key]), stage_of=getattr(approach, "stage_of", None), overrides=overrides)
        vals = {n: other.best(n, base[n]) for n, k in other.knobs.items() if k.control == "free" and n in base and other.state["values"].get(n)}
        if not vals:
            continue
        tr = getattr(approach, "translate_prior", None)
        if callable(tr):
            try:
                vals = tr(vals, goal_state[key])
            except Exception:  # noqa: BLE001
                pass
        return vals, key
    return None, None
