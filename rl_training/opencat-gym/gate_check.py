"""Deterministic gate for the vision-goal campaign. Reads a benchmark_goal JSON
(+ optionally a tfevents dir for the reward-collapse check) and prints one of:
    GO_20M    turning works well enough -> launch the fresh 20M
    RETUNE    marginal -> one retune pass
    STOP      turning failed -> stop, write recommendation

  python gate_check.py trained/smoke_goal.json [trained/tensorboard_logs/PPO_NNN]
"""
import glob
import json
import os
import sys

j = json.load(open(sys.argv[1]))
by = {int(g["bearing_deg"]): g for g in j["goals"]}
cruise = j["no_goal_cruise"]

reach = {b: by[b]["reach_rate"] for b in (0, 45, 90, 135, 180) if b in by}
drift = cruise["heading_drift_deg"]
cfall = cruise["fall_rate"]

reward_ok = True
reason_rw = ""
if len(sys.argv) > 2 and os.path.isdir(sys.argv[2]):
    try:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
        ea = EventAccumulator(sys.argv[2]); ea.Reload()
        s = [x.value for x in ea.Scalars("rollout/ep_rew_mean")]
        if s and s[-1] < 0.55 * max(s):
            reward_ok = False
            reason_rw = f" reward collapsed ({max(s):.0f}->{s[-1]:.0f})"
    except Exception as e:  # noqa: BLE001
        reason_rw = f" (reward check skipped: {e})"

lines = [f"reach 0/45/90/135/180 = " + "/".join(f"{reach.get(b,0):.0%}" for b in (0,45,90,135,180)),
         f"no-goal drift {drift:.1f}deg   cruise fall {cfall:.0%}{reason_rw}"]

if reach.get(0, 0) < 0.30:
    decision = "STOP"
    lines.append("-> STOP: goal-reach <30% dead ahead; the blend did not enable turning")
elif (reach.get(0, 0) >= 0.60 and reach.get(45, 0) >= 0.60 and reach.get(90, 0) >= 0.60
      and reach.get(135, 0) >= 0.40 and reach.get(180, 0) >= 0.40
      and drift < 15.0 and cfall <= 0.08 and reward_ok):
    decision = "GO_20M"
    lines.append("-> GO_20M: turning + heading-hold + gait health all clear")
else:
    decision = "RETUNE"
    lines.append("-> RETUNE: partial turning / marginal metric -- one retune pass")

print("\n".join(lines))
print(f"DECISION={decision}")
