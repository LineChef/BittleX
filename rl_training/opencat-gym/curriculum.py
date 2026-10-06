"""The difficulty-level update rule of train.py's Curriculum callback, as a pure function so it can be tested (V3 plan, docs/rl/v3-retrain-plan.md section 5b).

update_levels() takes the probe's results for one round and changes `levels` / `streak` in place:
  * clean-floor score `base` below `collapse_base`: the policy is failing even with no hazards, so EVERY category drops one step;
  * a category whose RELATIVE score (its raw score over the clean-floor score) is >= `up`, while `base` is at least `min_base`, counts a good probe; `windows` good
    probes in a row raise it one step (a weak clean-floor score blocks promotion: a policy that is not good in absolute terms is not ready for more);
  * a category at or below `down` drops one step; anything in between holds;
  * no category may exceed `cap` (a time-based ceiling: the levels may run slower than the validated pace, never faster).
"""


def update_levels(levels, streak, rel, base, cap, up, down, step, windows, min_base, collapse_base):
    for c in levels:
        if base < collapse_base:
            streak[c] = 0
            levels[c] = max(0.0, levels[c] - step)
        elif rel[c] >= up and base >= min_base:
            streak[c] += 1
            if streak[c] >= windows:
                levels[c] = min(1.0, levels[c] + step)
                streak[c] = 0
        else:
            streak[c] = 0
            if rel[c] <= down:
                levels[c] = max(0.0, levels[c] - step)
        levels[c] = min(levels[c], cap)
    return levels
