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
    # the body: 269 g URDF x 1.12 (alloy servos) + the case payload (spine 86 g, camera 15 g front, speaker 20 g rear) = 422 g
    "G2E_BODY_MASS_SCALE": "1.12", "G2E_PAYLOAD_PROFILE": "case",
    # calibration error and mount tilt seen at bring-up
    "G2E_IMU_BIAS_DEG": "2", "G2E_JOINT_OFFSET_DEG": "2",
    "G2E_SERVO_RATE_LIMIT_DEG_S": "137",       # borrowed from another project; Phase 0 step 4 measures G2's (backlog H13)
    "G2E_SLOPE_TARGET_PROB": "0.3",
    # validated reward tuning (V2 -> V2.1): yaw tracking 9, residual smoothing 10.5
    "G2E_FAC_YAW_TRACK": "9.0", "G2E_FAC_RESID_SMOOTH": "10.5",
    # the V2 course minus carpet (carpet is out of every gate and out of training; its own session later)
    "G2E_LEDGE_HEIGHT": "0.035", "G2E_LEDGE_RANDOMIZE": "1",
    "G2E_SURFACE_TRANSITION_PROB": "0", "G2E_SNAG_OBSTACLE_PROB": "0", "G2E_LEDGE_PROB": "0",
}

# --- Phase 1 output: parameters fitted so the sim matches the real walks. Empty until Phase 1 runs. ---
CALIBRATION: dict[str, str] = {}

# --- screening levers: one per 3M round (docs/rl/v3-retrain-plan.md sections 2.3-2.5) ---
LEVERS = {
    "mirror": {"G2E_MIRROR_LOSS": "1.0", "G2E_MIRROR_VALUE_LOSS": "0.1"},                      # R1 (train.py reads these)
    "heading_obs": {"G2E_HEADING_OBS": "1"},                                                   # Y2 (the Pi needs the same inputs)
    "heading_shape": {"G2E_FAC_HEADING_B": "3.0", "G2E_HEADING_SIGMA_DEG": "10"},              # R2
    "long_episodes": {"G2E_LONG_EP_PROB": "0.25", "G2E_LONG_EP_LEN": "1000"},                  # Y3
    "turn": {"G2E_TRAIN_YAW": "0.15"},                                                         # Y4 (only if Phase 1's turning gate passes)
    "faults": {"G2E_FAULT_STUCK_PROB": "0.10", "G2E_FAULT_WEAK_PROB": "0.10", "G2E_FAULT_OFFSET_PROB": "0.10",   # Y5
               "G2E_MOTOR_SCALE_RAND": "0.12", "G2E_DRIFT_TORQUE": "0.25", "G2E_DRIFT_PROB": "0.10"},
    "servo_feas": {"G2E_FAC_SERVO_FEAS": "5.0", "G2E_SERVO_CEIL_DEG_S": "137"},                # R3 (ceiling follows the measured servo speed)
    "balance_pbrs": {"G2E_FAC_BALANCE_PBRS": "4.0"},                                           # R4
    "smooth": {"G2E_FAC_SMOOTH_1": "15", "G2E_FAC_SMOOTH_2": "15"},                            # R5 (revised: the old terms are inert)
    "touchdown": {"G2E_FAC_TOUCHDOWN": "25"},                                                  # R6
}

# --- the staged chain (cumulative course settings); K3 is stage s0 ---
STAGES = [
    ("s0_flat", {}),
    ("s1_transition", {"G2E_SURFACE_TRANSITION_PROB": "0.25"}),
    ("s2_step", {"G2E_SURFACE_TRANSITION_PROB": "0.25", "G2E_SURFACE_TRANSITION_STEP_M": "0.012"}),
    ("s3_snag", {"G2E_SURFACE_TRANSITION_PROB": "0.25", "G2E_SURFACE_TRANSITION_STEP_M": "0.012", "G2E_SNAG_OBSTACLE_PROB": "0.20"}),
    ("s4_ledge", {"G2E_SURFACE_TRANSITION_PROB": "0.25", "G2E_SURFACE_TRANSITION_STEP_M": "0.012", "G2E_SNAG_OBSTACLE_PROB": "0.20",
                  "G2E_LEDGE_PROB": "0.20"}),
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
    if stage in LATE_STAGES:
        if "turn" in levers:
            out["G2E_TRAIN_YAW"] = "0.45"
        if stage == "s6_full_strength":
            if "faults" in levers:
                out.update(FULL_FAULTS)
            out.update(FINAL_EXTRA)
    return out


# settings that only make sense while training; scoring never uses them
TRAIN_ONLY_PREFIXES = ("G2E_MIRROR", "G2E_HARD_SCALE", "G2E_RAMP", "G2E_FAULT_", "G2E_LONG_EP", "G2E_DRIFT_", "G2E_MOTOR_SCALE_RAND",
                       "G2E_SLOPE_TARGET_PROB", "G2E_LEDGE_", "G2E_SURFACE_", "G2E_SNAG_", "G2E_TRAIN_YAW")


def env_for(*lever_names: str, stage: str | None = None, extra: dict | None = None) -> dict:
    """The G2E_* environment for a training run: RECIPE + CALIBRATION + levers + (a stage's course settings) + extra."""
    out = dict(RECIPE)
    out.update(CALIBRATION)
    for name in lever_names:
        out.update(LEVERS[name])
    if stage is not None:
        out.update(stage_extra(stage, lever_names))
    if extra:
        out.update(extra)
    return out


def scoring_env(*lever_names: str) -> dict:
    """The physical setup for scoring: RECIPE + CALIBRATION, minus training-only settings. Levers that change the observation or the
    reward geometry a policy was trained with (heading_obs) must be passed so the scoring env builds the same inputs."""
    out = {k: v for k, v in {**RECIPE, **CALIBRATION}.items() if not k.startswith(TRAIN_ONLY_PREFIXES)}
    for name in lever_names:
        if name == "heading_obs":
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
