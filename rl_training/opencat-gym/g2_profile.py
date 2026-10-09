"""One definition of "G2 as the sim should model it", for training and every scorer (V3 plan, docs/rl/v3-retrain-plan.md section 2.1).

Until 2026-10-06 the real-robot setup lived in four places that disagreed (run_pipeline.BASE, run_pipeline._score_checkpoint /
phase_c_report's hard-coded lines, benchmark_decathlon --hw, drift_probe.BASE_ENV). Everything V3 trains or scores takes its environment
variables from here:

    import g2_profile
    g2_profile.set_environ(g2_profile.env_for("mirror", "heading_shape"))     # BEFORE importing opencat_gym_env
    # or, for a subprocess:  env = {**os.environ, **g2_profile.env_for(...)}

`env_for(*lever_names, stage=...)` = RECIPE + CALIBRATION + the named levers' settings (+ a stage's cumulative course settings).
CALIBRATION is filled in by Phase 1 (sim calibration against the real walks); until then it holds the pre-calibration values.
Scoring uses `scoring_env()` = the same physical setup without training-only settings (hard-scale, ramp, mirror loss) and without levers.
"""
from __future__ import annotations

import os

# --- the base recipe: what V2 / V2.1 were trained with, plus the measured 422 g case payload (2026-10-06) ---
RECIPE = {
    # the real control path: stock firmware's 5 Hz IMU print with no gyro, joints sent with `i` every 3rd control tick
    "G2E_IMU_HOLD_STEPS": "16", "G2E_IMU_RATE_ZERO": "1", "G2E_CMD_PATH": "i", "G2E_CMD_PATH_EXTRA_MS_MAX": "4",
    "G2E_CMD_SEND_EVERY_N": "3",
    # the body: the base robot plus the case payload, 422 g in total (one weighing); the split between base and payload is the line below
    # 2026-10-07: the payload was weighed (168 g: Pi, PiSugar, camera, speaker, mic, wiring, lid; 100 x 40 x 38 mm block, centered): profile "case2", base 254 g = 269 g x 0.944.
    # Runs started before 2026-10-07 used the old split ("case", scale 1.12: 301 g base + 121 g payload); see docs/rl/v3-decisions-log.md.
    "G2E_BODY_MASS_SCALE": "0.944", "G2E_PAYLOAD_PROFILE": "case2",
    # calibration error and mount tilt seen at bring-up
    # IMU, measured 2026-10-07 after the firmware gyro calibration (`gc`), G2 standing still with the firmware balance off (docs/rl/real-walk-log.md "IMU after the gyro calibration"):
    # roll zero error -0.69 deg, pitch -0.07 deg, noise sd 0.09 / 0.08 deg (so about 0.0008 in the quaternion), yaw drift 0.000 deg/s at rest, frames every 0.20 s (5 Hz: IMU_HOLD_STEPS 16).
    # Before that: bias +-2 deg, quaternion noise 0.02 (IMU_WORLD_A below). The joint offset is the servo calibration, unchanged.
    "G2E_IMU_BIAS_DEG": "0.7", "G2E_RANDOM_GYRO": "0.001", "G2E_JOINT_OFFSET_DEG": "2",
    "G2E_SERVO_RATE_LIMIT_DEG_S": "137",       # borrowed from another project; Phase 0 step 4 measures G2's (backlog H13)
    "G2E_SLOPE_TARGET_PROB": "0.3",
    # validated reward tuning (V2 -> V2.1): yaw tracking 9, residual smoothing 10.5
    # reward tuning: yaw tracking 9 (V2.1). The residual-smoothing weight is 8.2 for FRESH runs and 10.5 from the continuation stages on (stage_extra): the V2 -> V2.1 value
    # was tuned on an already-quiet policy; on a young one (exploration noise std 0.5-1.0) it costs -4 to -7 per step and swamps the reward (C0 run 1, 2026-10-06).
    "G2E_FAC_YAW_TRACK": "9.0", "G2E_FAC_RESID_SMOOTH": "8.2",
    # Both ramps (the reward penalties and the generic randomization: IMU noise and bias, mass, friction, calibration error ...) run over 4M total steps, the pace every
    # validated run actually had (the old per-env ramp reached 1.0 only at 8 x 5e5 total steps). C0 run 2 with the randomization at full strength from 1M steps survived only
    # 56% of clean-floor episodes at 1.4M steps. Continuation stages start at full strength (train.py ramp offset).
    "G2E_RAMP_PENALTY_STEPS": "4e6", "G2E_RAMP_TOTAL_STEPS": "4e6",
    # the V2 course minus carpet (carpet is out of every gate and out of training; its own session later)
    "G2E_LEDGE_HEIGHT": "0.035", "G2E_LEDGE_RANDOMIZE": "1",
    "G2E_SURFACE_TRANSITION_PROB": "0", "G2E_SNAG_OBSTACLE_PROB": "0", "G2E_LEDGE_PROB": "0",
    # difficulty scaling (2026-10-06): every hazard scales with a per-category level that rises only where the policy is ready (terrain / ledge / slope / fault),
    # starting from a clean passable floor; see opencat_gym_env CATEGORY_LEVELS. 8 focus episodes per +0.05 step, up at >= 85% survived-with-progress, down at <= 60%.
    "G2E_ADAPTIVE_LEVEL": "1", "G2E_CATEGORY_LEVELS": "1", "G2E_SCALE_ALL_HAZARDS": "1",
    # Pace of the climb, per category (a window = that category's focus episodes; ~16% of all episodes are focus episodes of any one category). The screening runs are
    # only 3M steps, so they climb quickly: +0.10 after ONE good window of 6 (the hold at each new level is one window, ~75k steps across 8 envs; full difficulty needs
    # >= ~0.75M steps even for a perfect policy). Continuation stages and the 20M climb carefully (see stage_extra): +0.05 after TWO good windows of 8 (~200k steps each).
    "G2E_LEVEL_WINDOW_C": "6", "G2E_LEVEL_STEP_C": "0.10", "G2E_LEVEL_PROMOTE_WINDOWS": "1",
    # Competence is measured by a deterministic probe every 98k steps (12 episodes per category from S2 on; C0 and S1 used 6, so their level paths are noisier), not from the noisy training episodes: see train.py Curriculum.
    # The probe score is RELATIVE to the same policy's clean-floor score (same randomization), so up/down thresholds judge hazard handling only.
    "G2E_LEVEL_CAP_BY_TIME": "1", "G2E_LEVEL_MAX": "1.25", "G2E_LEVEL_MIN_BASELINE": "0.5", "G2E_LEVEL_COLLAPSE_BASELINE": "0.35",
    # record about one training episode in 50 so it can be watched exactly as it happened (episode_recorder.py, watch_training.py); the newest 80 are kept per run
    "G2E_RECORD_EVERY": "50",
    "G2E_LEVEL_EXTERNAL": "1", "G2E_PROBE_EVERY": "98304", "G2E_PROBE_EPISODES": "12", "G2E_LEVEL_UP_SCORE": "0.80", "G2E_LEVEL_DOWN_SCORE": "0.50",
    # 2026-10-08 training upgrade, applied directly (no change to what the policy learns, or a correction too small to screen; docs/plan-detail/handoff-2026-10-08.md 12):
    # 6 env processes (the M1 Pro's performance cores), only the needed info between processes, the eval / best-checkpoint / health monitor every 1M steps,
    # IMU noise held for each 5 Hz frame (as on G2), and the paw slip / clearance penalties weighted by paw velocity (they read the paw's x position).
    "G2E_N_ENVS": "6", "G2E_LEAN_INFO": "1", "G2E_RUN_MONITOR": "1", "G2E_IMU_NOISE_PER_FRAME": "1", "G2E_FIX_PAW_VEL": "1",
}

# the IMU settings every run before 2026-10-07 (about 9:30 AM) used; queue jobs that must stay in that world set them through their "extra"
IMU_WORLD_A = {"G2E_IMU_BIAS_DEG": "2", "G2E_RANDOM_GYRO": "0.02"}

# --- Phase 1 output: parameters fitted so the sim matches the real walks. Empty until Phase 1 runs. ---
CALIBRATION: dict[str, str] = {
    # 2026-10-06 (Phase 1, fast pass): V2.1 on benchmark_v4 cell N1 (12.5 s calm walk) matched to the 14 post-servo-swap real walks
    # (roll std 5.14, pitch std 2.41, 0 falls, heading +36 +- 25 right). Sweep data: docs/rl/v3-data/calibration/. Chosen 200 deg/s + 0.15 N*m:
    # 0% falls, roll 4.59 (-11%), pitch 2.57 (+7%), speed 0.090 (G2 ~0.120: a known residual gap, handled by scaling the commanded speed on the Pi),
    # heading -4 (G2 -36 +- 25). Raising ground / foot friction or the servo gains did not help (stiffer gains made every episode fall).
    "G2E_SERVO_RATE_LIMIT_DEG_S": "200",
    "G2E_MOTOR_FORCE": "0.15",
}

# --- screening levers: one per 3M round (docs/rl/v3-retrain-plan.md sections 2.3-2.5) ---
LEVERS = {
    "mirror": {"G2E_MIRROR_LOSS": "1.0", "G2E_MIRROR_VALUE_LOSS": "0.1"},                      # R1 (train.py reads these)
    "mirror_strong": {"G2E_MIRROR_LOSS": "2.0", "G2E_MIRROR_VALUE_LOSS": "0.2"},                 # 2026-10-09 (user): twice the mirror weight in every run after the first long-hazard run; the 20M mirror gap rose to 0.09 (V3: 0.039)
    "heading_obs": {"G2E_HEADING_OBS": "1"},                                                   # Y2 (the Pi needs the same inputs)
    "heading_shape": {"G2E_FAC_HEADING_B": "3.0", "G2E_HEADING_SIGMA_DEG": "10"},              # R2
    "long_episodes": {"G2E_LONG_EP_PROB": "0.25", "G2E_LONG_EP_LEN": "1000"},                  # Y3
    "turn": {"G2E_TRAIN_YAW": "0.15"},                                                         # Y4 (only if Phase 1's turning gate passes)
    "faults": {"G2E_FAULT_STUCK_PROB": "0.10", "G2E_FAULT_WEAK_PROB": "0.10", "G2E_FAULT_OFFSET_PROB": "0.10",   # Y5
               "G2E_MOTOR_SCALE_RAND": "0.12", "G2E_DRIFT_TORQUE": "0.25", "G2E_DRIFT_PROB": "0.10"},
    "servo_feas": {"G2E_FAC_SERVO_FEAS": "5.0", "G2E_SERVO_CEIL_DEG_S": "200"},                # R3 (ceiling = the calibrated servo speed)
    "balance_pbrs": {"G2E_FAC_BALANCE_PBRS": "4.0"},                                           # R4
    "smooth": {"G2E_FAC_SMOOTH_1": "15", "G2E_FAC_SMOOTH_2": "15"},                            # R5 (revised: the old terms are inert)
    "length_level": {"G2E_LENGTH_LEVEL": "1"},                                                    # S11 (2026-10-07): the length difficulty level, with a balanced yaw push on every long episode; see opencat_gym_env LENGTH_LEVEL
    "touchdown": {"G2E_FAC_TOUCHDOWN": "25"},
    # 2026-10-07 (user): no command-drift training. no_heading drops the accumulated-heading penalty; yaw_damp doubles the yaw-rate damping (FAC_YAW_TRACK is a pure yaw-rate penalty while cmd_yaw is 0: 9 -> 18).
    "no_heading": {"G2E_FAC_HEADING": "0"},
    "yaw_damp": {"G2E_FAC_YAW_TRACK": "18.0"},                                                  # R6
    # 2026-10-08 training upgrade, screened one at a time (two seeds each) by phase_v4.py:
    "big_batch": {"G2E_PPO_BATCH": "4096", "G2E_PPO_EPOCHS": "5"},                               # 20 gradient steps per rollout instead of 2,560
    "frontier": {"G2E_FRONTIER": "1", "G2E_CAP_SIDEHILL_DEG": "0", "G2E_CAP_UPHILL_DEG": "0",      # per-hazard frontier curriculum (physical bounds; caps file = manual override)
                 "G2E_CAP_DOWNHILL_DEG": "0", "G2E_CAP_LEDGE_M": "0"},
    "cmd_forward": {"G2E_CMD_BANDS": "forward"},                                                 # no backward, no unreachable fast band (user: drop backward)
    "cmd_capped": {"G2E_CMD_BANDS": "capped"},                                                   # ablation of cmd_forward: only the unreachable fast band is removed, backward stays
    "opt_bundle": {"G2E_NORM_REWARD": "1", "G2E_LOG_STD_INIT": "-1", "G2E_LR_FLOOR": "0.1"},     # reward normalization, std 0.37 start, LR floor 3e-5
    "hazard_contact": {"G2E_HAZARD_EP_LEN": "375"},                                              # hazard-focus episodes 4.7 s, obstacles spread to match
    "slope_floor": {"G2E_FRONTIER_FLOOR": "sidehill:5,climb:4,descent:4"},                       # 2026-10-09: V3-proven sizes (10 deg side-hill, 12 deg climb, 10.8 deg descent) are the minimum frontier for the slopes
    "lr_half": {"G2E_LR_SCALE": "0.5"},                                                         # 2026-10-09: the clip fraction was above 0.3 in every long run (0.33-0.49): half the learning rate
    "hazard_long": {"G2E_HAZARD_EP_LEN": "600", "G2E_HAZARD_X_SCALE": "1.0"},                    # hazard-focus episodes 7.5 s with the obstacles where they were: G2 gets time to walk through them
    "imitation_actual": {"G2E_IMITATION_ACTUAL": "1"},                                           # imitation on measured joints (recipe evaluation finding 1)
    "privileged_critic": {"G2E_PRIV_OBS": "1"},                                                  # critic-only true state + hazards (recipe evaluation finding 3)
}
# Levers that change what the POLICY observes: a policy trained with one must be scored with it (scoring_env, benchmark_v4.ladder_env, phase_v3.policy_levers).
OBS_LEVERS = ("heading_obs", "privileged_critic")
# Settings only train.py reads (how training runs, not the world): never part of a scoring or ladder environment.
TRAINER_ONLY_PREFIXES = ("G2E_N_ENVS", "G2E_LEAN_INFO", "G2E_RUN_MONITOR", "G2E_MONITOR_EVERY", "G2E_PLATEAU", "G2E_PPO_", "G2E_NORM_REWARD", "G2E_LOG_STD_INIT",
                         "G2E_LR_FLOOR", "G2E_FRONTIER", "G2E_HAZARD_EP_LEN", "G2E_HAZARD_X_SCALE", "G2E_LR_SCALE", "G2E_FRONTIER_FLOOR", "G2E_CMD_BANDS", "G2E_SEED", "G2E_TORCH_THREADS")

# --- the staged chain (cumulative course settings); K3 is stage s0 ---
# The SURFACE STEP / TRANSITION (a hard floor turning into a soft, high-friction carpet-like slab with a 12 mm step) is taken out of the training course COMPLETELY (user, 2026-10-08): no stage,
# no course and no recipe switches it on. s1_transition and s2_step keep their names (queue jobs refer to stages by name) but are now empty. The generator stays in opencat_gym_env only because
# benchmark cells T4.1 and T4.2 measure it as a test; nothing trains on it.
STAGES = [
    ("s0_flat", {}),
    ("s1_transition", {}),
    ("s2_step", {}),
    ("s3_snag", {"G2E_SNAG_OBSTACLE_PROB": "0.20"}),
    ("s4_ledge", {"G2E_SNAG_OBSTACLE_PROB": "0.20", "G2E_LEDGE_PROB": "0.20"}),
]
# The two stages after the course is built. Their extra settings apply only when the lever they harden was kept (see stage_extra()).
LATE_STAGES = ["s5_turn_wide", "s6_full_strength"]
FULL_FAULTS = {"G2E_FAULT_STUCK_PROB": "0.20", "G2E_FAULT_WEAK_PROB": "0.20", "G2E_FAULT_OFFSET_PROB": "0.20", "G2E_MOTOR_SCALE_RAND": "0.15",
               "G2E_DRIFT_TORQUE": "0.30", "G2E_DRIFT_PROB": "0.20"}
FINAL_EXTRA = {"G2E_HARD_SCALE": "1.10"}     # the hardest training levels +10% (shoves, slopes, overheat cutback, obstacle / rubble heights)


def stage_extra(stage: str, levers) -> dict:
    """Course-stage settings (cumulative) for any stage name, including the late ones. s5 widens the turn range (needs the turn lever);
    s6 is full-strength faults (needs the faults lever), the wide turn range, and the +10% hard levels."""
    out = dict(dict(STAGES)["s4_ledge"]) if stage in LATE_STAGES else dict(dict(STAGES)[stage])
    if stage != "s0_flat":
        out["G2E_LEVEL_START"] = "0.8" if stage != "s6_full_strength" else "1.0"     # a continuation must not restart from an empty floor
        out.update({"G2E_LEVEL_WINDOW_C": "8", "G2E_LEVEL_STEP_C": "0.05", "G2E_LEVEL_PROMOTE_WINDOWS": "2"})   # the careful pace: +0.05 after 2 good probes in a row
        out["G2E_FAC_RESID_SMOOTH"] = "10.5"                  # the V2.1 smoothing weight, now that the policy is quiet
    if stage in LATE_STAGES:
        if "turn" in levers:
            out["G2E_TRAIN_YAW"] = "0.45"
        if stage == "s6_full_strength":
            if "faults" in levers:
                out.update(FULL_FAULTS)
            out.update(FINAL_EXTRA)
    return out


# settings that only make sense while training; scoring never uses them
TRAIN_ONLY_PREFIXES = TRAINER_ONLY_PREFIXES + ("G2E_RECORD", "G2E_ADAPTIVE_LEVEL", "G2E_CATEGORY_LEVELS", "G2E_SCALE_ALL", "G2E_LEVEL_", "G2E_MIRROR", "G2E_HARD_SCALE", "G2E_RAMP", "G2E_FAULT_", "G2E_LONG_EP", "G2E_DRIFT_", "G2E_MOTOR_SCALE_RAND",
                       "G2E_SLOPE_TARGET_PROB", "G2E_LEDGE_", "G2E_SURFACE_", "G2E_SNAG_", "G2E_TRAIN_YAW")


# World 2 (user, 2026-10-07): the payload block the spine's size and centred on it, with only the camera and the speaker hanging past it (see opencat_gym_env PAYLOAD_LAYOUT); this also puts the sim's front share near 46%, matching the two weighings (45% and 47%). It applies to trainings
# started AFTER the V3 queue (S8, S9, K3 and the 20M are judged against a control in world 1): switch it on with `touch trained/v3_world2` or G2_WORLD=2 (a restarted runner picks it up).
WORLD2_CALIBRATION = {"G2E_PAYLOAD_LAYOUT": "spine"}      # (the 1.25 level ceiling is in RECIPE: every run started from now on may earn levels up to 1.25, user 2026-10-07)


# --- the approved real-hardware calibration snapshot (tools/g2_calibrate.py, docs/rl/real-data-pipeline.md): fitted from G2's own logs, loaded only once approved ---
CAL_WHITELIST = ("G2E_IMU_HOLD_STEPS", "G2E_CMD_PATH_EXTRA_MS_MAX")       # the builder's whole list; anything else in a snapshot file is ignored


def calibration_snapshot() -> tuple[dict, str | None]:
    """(settings, snapshot id) of the approved snapshot, or ({}, None): no snapshot approved, `G2_CAL_SNAPSHOT=off`, or any problem reading it."""
    if os.environ.get("G2_CAL_SNAPSHOT", "on").lower() in ("off", "0", "no"):
        return {}, None
    try:
        import json
        base = os.path.join(os.path.expanduser(os.environ.get("G2_DATA_DIR", "~/g2_data")), "calibration")
        cid = int(json.load(open(os.path.join(base, "current.json")))["id"])
        env = json.load(open(os.path.join(base, "snapshots", f"{cid:04d}.json")))["env"]
        return {k: str(v) for k, v in env.items() if k in CAL_WHITELIST}, f"{cid:04d}"
    except Exception:  # noqa: BLE001 -- no snapshot is the normal case
        return {}, None


def world2() -> bool:
    return os.environ.get("G2_WORLD", "") == "2" or os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "trained", "v3_world2"))


def env_for(*lever_names: str, stage: str | None = None, extra: dict | None = None) -> dict:
    """The G2E_* environment for a training run: RECIPE + CALIBRATION + levers + (a stage's course settings) + extra."""
    out = dict(RECIPE)
    out.update(CALIBRATION)
    cal, cal_id = calibration_snapshot()
    out.update(cal)
    if cal_id:
        out["G2_CAL_ID"] = cal_id                 # the run records which real-data calibration it trained in
    if world2():
        out.update(WORLD2_CALIBRATION)
    for name in lever_names:
        out.update(LEVERS[name])
    if stage is not None:
        out.update(stage_extra(stage, lever_names))
    if extra:
        out.update(extra)
    return out


# The whole course in one place (user, 2026-10-08: every hazard enabled, in every run, unless there is a good reason): surface steps with a 12 mm step, snag obstacles and ledges, on top of the
# terrain / slope / fault categories. Each hazard still starts from a clean floor and ramps with its own difficulty level, so enabling it from the first step is gentle, and every level is
# limited to the measured top threshold (the G2E_CAP_* settings; docs/rl/passability-audit.md).
# The share of training episodes each challenge appears in (user, 2026-10-08, measured by sampling the reset: rubble 50%, box obstacles 30%, slopes of 5 deg or more 20%, rough floor 20%,
# snag obstacles 20%, ledges 20%). The settings are the per-episode chances that give those shares after the episode mix (10% hazard-free anchors, focus and combo episodes), tuned with
# the sampler in passability_audit.py `mix`; they apply to new fresh finals only (old runs and the benchmark cells keep their own).
FULL_COURSE = {"G2E_RUBBLE_PROB": "0.575", "G2E_RANDOM_TERRAIN_PROB": "0.34", "G2E_ROUGH_TERRAIN_PROB": "0.25", "G2E_SLOPE_TARGET_PROB": "0.14", "G2E_SLOPE_MAX_DEG": "10",
               "G2E_SNAG_OBSTACLE_PROB": "0.228", "G2E_LEDGE_PROB": "0.28",
               # PROVISIONAL top-threshold caps (start values from the capability test, 2026-10-08; docs/rl/next-20m-plan.md). They are adjustable while the run trains
               # (trained/<tag>_caps.json) and reviewed every 1M steps with caps_report.py: too low and the policy never improves, too high and it cannot learn to succeed.
               "G2E_CAP_SIDEHILL_DEG": "8", "G2E_CAP_UPHILL_DEG": "10", "G2E_CAP_DOWNHILL_DEG": "10", "G2E_CAP_LEDGE_M": "0.02"}
# The surface step (a hard floor that turns into a carpet-like slab with a 12 mm step) is deliberately NOT in the course: user, 2026-10-08, "don't re-enable surface step". Carpet-like physics stays out of
# training (CARPET, CARPET_SOFT and the rug are off too). Its floor bug is fixed and its benchmark cells (T4.1, T4.2) still measure it, so it can be switched on later with one line.

# Finals that already ran WITHOUT the staged hazards, kept honest: the 20M of 2026-10-08 was launched as a fresh run on the flat stage by mistake (dropping the chain also dropped the
# surface steps, snags and ledges it was meant to introduce), so its viewer environment is the flat one. Nothing new is added to this set.
HISTORICAL_FLAT_FINALS = {"v3_20m"}
# The careful climb (RECIPE: "Continuation stages and the 20M climb carefully"): +0.05 after two good probes in a row, not the screening pace (+0.10 after one). 2026-10-08 review:
# since the 20M became a FRESH s0_flat run it silently got the 3M screening pace, so each single noisy probe moved a level by 0.10 (the finished 20M's slope level fell
# 0.90 -> 0.80 -> 0.70 in two probes at 19.9M). New fresh finals get the careful pace; v3_20m keeps what it ran with.
FINAL_PACE = {"G2E_LEVEL_WINDOW_C": "8", "G2E_LEVEL_STEP_C": "0.05", "G2E_LEVEL_PROMOTE_WINDOWS": "2"}


def env_for_job(job: dict) -> dict:
    """THE training environment of a queue job (phase_v3.train launches with exactly this; the viewers use it too, so what you watch is what trains).
    A fresh final (the 20M) is stage s0_flat plus FULL_COURSE (every hazard, with the caps), the careful climb (FINAL_PACE) and the hard-levels factor; the historical
    flat finals keep the flat stage. A stage job adds its course settings."""
    levers = job.get("levers", [])
    kind = job["kind"]
    if kind == "stage":
        return env_for(*levers, stage=job["stage"], extra=job.get("extra"))
    if kind == "final" and job.get("fresh"):
        course = {} if job.get("tag") in HISTORICAL_FLAT_FINALS else dict(FULL_COURSE, **FINAL_PACE, G2E_PLATEAU_STOP="1")      # plateau stop on long runs (user, 2026-10-08)
        return env_for(*levers, stage="s0_flat", extra=dict(course, **FINAL_EXTRA, **(job.get("extra") or {})))
    if kind == "final":
        return env_for(*levers, stage=job["stage"], extra=job.get("extra"))
    return env_for(*levers, extra=job.get("extra"))


def next_final_env(levers=("mirror",)) -> dict:
    """The training environment of the next fresh final (what the audits and the cap tests check, so what is audited is what trains)."""
    return env_for_job({"kind": "final", "tag": "next_fresh_final", "fresh": True, "levers": list(levers)})


def scoring_env(*lever_names: str) -> dict:
    """The physical setup for scoring: RECIPE + CALIBRATION, minus training-only settings. Levers that change the observation or the
    reward geometry a policy was trained with (heading_obs) must be passed so the scoring env builds the same inputs."""
    out = {k: v for k, v in {**RECIPE, **CALIBRATION, **calibration_snapshot()[0], **(WORLD2_CALIBRATION if world2() else {})}.items() if not k.startswith(TRAIN_ONLY_PREFIXES)}
    for name in lever_names:
        if name in OBS_LEVERS:
            out.update(LEVERS[name])
    return out


def set_environ(env: dict) -> None:
    """Put the settings in os.environ (call BEFORE importing opencat_gym_env, which reads them at import)."""
    for k, v in env.items():
        os.environ[k] = str(v)


def policy_levers_from_sidecar(path: str) -> list[str]:
    """Which observation-changing levers a trained policy needs at scoring time, read from its .onnx.json or a `<policy>.levers` file;
    empty for policies without one."""
    import json
    for cand in (path + ".levers", path + ".onnx.json"):
        if os.path.exists(cand):
            try:
                return list(json.load(open(cand)).get("levers", []))
            except Exception:  # noqa: BLE001
                return []
    return []
