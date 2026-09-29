"""Cheap 3M diagnostic (2026-09-29): is r5_hw_candidate's yaw/drift/ledges
regression actually about tick-to-tick observation noise, not the real IMU
rate itself? Continues from r5_hw_candidate (IMU_HOLD_STEPS=1, trained 20M)
for 3M more steps with IMU_HOLD_STEPS=4 (~20 Hz -- a middle ground between
the old stale 5 Hz and the fully-fresh-every-tick 80 Hz) -- everything else
identical. If yaw/drift/ledges improve meaningfully from this alone, that
confirms noise-sensitivity as the mechanism and justifies building an
explicit observation-smoothing filter (the real fix) rather than reverting
accuracy. If it doesn't help, the hypothesis is wrong and something else is
going on.

Not a rigorous equal-budget comparison (r5_hw_candidate itself has a full
20M behind it, this checkpoint only 3M more) -- it's a directional probe:
does a small nudge in this one knob, from the SAME already-converged
starting point, move the metrics at all.

    python phase_r7_holdsteps_probe.py
"""
import glob
import json
import time

import run_pipeline as RP

LOG = "trained/phase_r7_holdsteps_probe.log"
STEPS = "3e6"
TAG = "r7_holdsteps4_probe"
FROM_CKPT = "trained/r5_hw_candidate_ppo"
ALL_CELLS = ["T4.1", "T4.2", "T10.1", "T7.2", "T5.1", "T5.2", "T5.3"]

# r5_hw_candidate's own already-measured numbers (trained/phase_r5_hw_gate_decision.json
# and trained/phase_r5_hw_sequential_report.json), the baseline this probe compares against.
BASELINE = dict(
    yaw_rms=6.481629001121694,
    heading_drift=9.671987351374847,
    ledges_fell=0.2333333333333333,
    flat_fell=0.0,
)


def log(msg):
    line = f"[r7probe {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _score_yaw(tag, step):
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench
    from opencat_gym_env import OpenCatGymEnv

    m = _load_learned(f"trained/checkpoints/{tag}_{step}_steps")
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    B._apply({})
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 4, True, "i"   # match this probe's training knob
    E.CMD_SEND_EVERY_N = 3
    E.EPISODE_LENGTH = 250
    s, _ = _bench(env, m, 20, 1000)
    env.close()
    return float(s["yaw_rate_rms_deg_mean"]), float(s["heading_drift_deg_mean"])


def _score_checkpoint_hold4(tag, step, all_cells):
    """Same as run_pipeline._score_checkpoint but with IMU_HOLD_STEPS=4 to
    match this probe's training config -- eval must match training."""
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench
    from opencat_gym_env import OpenCatGymEnv

    m = _load_learned(f"trained/checkpoints/{tag}_{step}_steps")
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    B._apply({})
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 4, True, "i"
    E.CMD_SEND_EVERY_N = 3
    E.EPISODE_LENGTH = 250
    s, _ = _bench(env, m, 20, 1000)
    fell, speed = float(s["fell_fraction"]), float(s["forward_speed_mps_mean"])

    skill_results = {}
    cells_all = {c[0]: c for c in B.LADDER}
    for cid in all_cells:
        knobs = {k: v for k, v in cells_all[cid][4].items() if not k.startswith("_")}
        B._apply(knobs)
        E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 4, True, "i"
        E.CMD_SEND_EVERY_N = 3
        E.EPISODE_LENGTH = 250
        s, _ = _bench(env, m, 20, 1000)
        skill_results[cid] = round(s["fell_fraction"], 3)
    env.close()
    return fell, speed, skill_results


def main():
    log("=== IMU_HOLD_STEPS=4 diagnostic probe started ===")
    log(f"baseline (r5_hw_candidate, HOLD_STEPS=1): {BASELINE}")
    env = {"G2E_IMU_HOLD_STEPS": "4"}
    RP.launch(TAG, env, steps=STEPS, from_ckpt=FROM_CKPT)
    ok, reason = RP.wait_for_finish(TAG)
    if not ok:
        log(f"HALT: {reason}")
        raise SystemExit(1)

    ckpts = sorted(glob.glob(f"trained/checkpoints/{TAG}_*_steps.zip"))
    final_step = max(int(p.rsplit("_", 2)[-2]) for p in ckpts) if ckpts else int(float(STEPS))
    flat_fell, flat_speed, skills = _score_checkpoint_hold4(TAG, final_step, ALL_CELLS)
    yaw_rms, drift = _score_yaw(TAG, final_step)
    ledges_fell = sum(skills[c] for c in ("T5.1", "T5.2", "T5.3")) / 3

    log(f"{TAG} @ {final_step}: T1.1 fell {flat_fell:.3f} speed {flat_speed:.4f}; "
        f"per-cell: {skills}")
    log(f"yaw_rms={yaw_rms:.2f} (baseline {BASELINE['yaw_rms']:.2f}), "
        f"drift={drift:.2f} (baseline {BASELINE['heading_drift']:.2f}), "
        f"ledges_fell={ledges_fell:.3f} (baseline {BASELINE['ledges_fell']:.3f})")

    yaw_improved = yaw_rms < BASELINE["yaw_rms"] - 0.3
    drift_improved = drift < BASELINE["heading_drift"] - 1.0
    ledges_improved = ledges_fell < BASELINE["ledges_fell"] - 0.03
    verdict = dict(yaw_improved=yaw_improved, drift_improved=drift_improved,
                   ledges_improved=ledges_improved, yaw_rms=yaw_rms, drift=drift,
                   ledges_fell=ledges_fell, flat_fell=flat_fell, skills=skills,
                   baseline=BASELINE)
    with open("trained/phase_r7_holdsteps_probe_result.json", "w") as f:
        json.dump(verdict, f, indent=2)

    hypothesis_confirmed = yaw_improved and drift_improved
    log(f"=== probe done -- yaw_improved={yaw_improved} drift_improved={drift_improved} "
        f"ledges_improved={ledges_improved} -- noise-sensitivity hypothesis "
        f"{'CONFIRMED' if hypothesis_confirmed else 'NOT confirmed'} "
        f"-- see trained/phase_r7_holdsteps_probe_result.json ===")


if __name__ == "__main__":
    main()
