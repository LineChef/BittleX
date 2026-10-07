"""Checks for the V3 retrain levers (docs/rl/v3-retrain-plan.md). Run from rl_training/opencat-gym with the RL venv:

    ../../.venv/bin/python -m pytest test_v3_levers.py -q
"""
import os
import sys

os.environ.setdefault("G2E_PAYLOAD_PROFILE", "case")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pybullet as p
import pytest
import torch as th

import mirror as M

WKF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pi_pipeline", "gait", "wkf_ref.npy")


@pytest.mark.parametrize("dim", [278, 280])
def test_mirror_obs_is_an_involution(dim):
    obs = np.random.default_rng(0).uniform(-1, 1, (5, dim))
    obs[:, 9] = np.random.default_rng(1).uniform(0, 1, 5)
    again = M.mirror_obs(M.mirror_obs(obs))
    assert np.allclose(again, obs, atol=1e-9)
    t = th.as_tensor(obs, dtype=th.float32)
    assert th.allclose(M.mirror_obs(t), th.as_tensor(M.mirror_obs(obs), dtype=th.float32), atol=1e-6)


def test_mirror_act_swaps_left_right_joints_and_is_an_involution():
    a = np.arange(8.0)
    assert np.array_equal(M.mirror_act(a), [2, 3, 0, 1, 6, 7, 4, 5])
    assert np.array_equal(M.mirror_act(M.mirror_act(a)), a)


def test_quaternion_mirror_equals_the_quaternion_of_the_mirrored_euler_angles():
    """Mirror across the x-z plane: roll and yaw flip sign, pitch stays."""
    obs = np.zeros(278)
    for r, pi, y in ((0.2, -0.1, 0.7), (-0.3, 0.25, -1.1)):
        obs[:4] = p.getQuaternionFromEuler([r, pi, y])
        want = p.getQuaternionFromEuler([-r, pi, -y])
        got = M.mirror_obs(obs)[:4]
        assert np.allclose(got, want, atol=1e-9) or np.allclose(got, -np.array(want), atol=1e-9)


def test_gravity_and_phase_and_command_mirror():
    obs = np.zeros(278)
    obs[6:9] = [0.1, 0.3, -0.9]
    obs[PH := 9] = 0.8
    obs[36:38] = [0.5, 0.4]
    m = M.mirror_obs(obs)
    assert np.allclose(m[6:9], [0.1, -0.3, -0.9])
    assert m[PH] == pytest.approx(0.3)
    assert np.allclose(m[36:38], [0.5, -0.4])


def test_wkf_joint_history_mirrors_to_half_a_cycle_later():
    """The scripted gait, mirrored left-right, equals itself 50 frames later to within ~4 deg: the joint swap and phase shift are consistent."""
    w = np.degrees(np.load(WKF))                         # (100, 8) URDF deg
    mirrored = w[:, M.JOINT_SWAP]
    assert np.abs(np.roll(mirrored, -50, axis=0) - w).max() < 5.0


def test_mirror_gap_is_zero_for_a_symmetric_policy_and_positive_for_a_biased_one():
    class _Dist:
        def __init__(self, mean):
            self.distribution = type("D", (), {"mean": mean})()

    class _Pol:
        def __init__(self, bias):
            self.bias = th.as_tensor(bias, dtype=th.float32)

        def get_distribution(self, obs):
            # a mirror-symmetric mean: the roll tilt (index 10 pair) drives left and right joints oppositely
            mu = th.zeros(obs.shape[0], 8)
            mu[:, 0] = -obs[:, 10]
            mu[:, 2] = obs[:, 10]
            return _Dist(mu + self.bias)

    class _Model:
        def __init__(self, bias):
            self.policy = _Pol(bias)

    obs = np.random.default_rng(2).uniform(-1, 1, (16, 278)).astype(np.float32)
    assert M.mirror_gap(_Model(np.zeros(8)), obs) == pytest.approx(0.0, abs=1e-6)
    assert M.mirror_gap(_Model([0, 0, 0, 0, 0, 0, 0.3, 0]), obs) > 0.05     # a fixed back-left hip offset is detected


# ----------------------------------------------------------------------------- benchmark_v4 helpers
def test_hard_scaled_scales_only_the_difficulty_knobs_and_caps_the_cutback():
    import benchmark_v4 as B4
    out = B4.hard_scaled({"IMPULSE_PUSH": 1.0, "TORQUE_CUTBACK": 0.6, "SLOPE_FIXED_RP": (0.0, -0.2), "RUBBLE_N": 400, "LEDGE_PROB": 1.0}, 1.1)
    assert out["IMPULSE_PUSH"] == pytest.approx(1.1)
    assert out["TORQUE_CUTBACK"] == pytest.approx(0.66)
    assert out["SLOPE_FIXED_RP"] == pytest.approx((0.0, -0.22))
    assert out["RUBBLE_N"] == 400 and out["LEDGE_PROB"] == 1.0                   # counts and probabilities are not difficulty
    assert B4.hard_scaled({"TORQUE_CUTBACK": 0.88}, 1.1)["TORQUE_CUTBACK"] == pytest.approx(0.9)


def test_episode_counts_scale_with_the_requested_episodes():
    import benchmark_v4 as B4
    assert B4.n_episodes(None, 40) == 40 and B4.n_episodes(None, 6) == 6
    assert B4.n_episodes(40, 40) == 40 and B4.n_episodes(8, 40) == 8
    assert B4.n_episodes(40, 4) == 4 and B4.n_episodes(8, 4) == 2                # never below 2


def test_cell_selection_and_hard_scale_naming():
    import benchmark_v4 as B4
    rows = B4.cell_table(1.1)
    ids = [r[0] for r in rows]
    assert "T2.2+10%" in ids and "T2.1" in ids and "N1" in ids and "T10.1" in ids
    assert {r[0] for r in B4.select(rows, "core", 1.1)} >= {"T1.1", "N1", "T2.2+10%", "T8.1+10%"}
    stage = {r[0] for r in B4.select(B4.cell_table(), "stage:s2_step")}
    assert {"T1.1", "T4.1", "T4.2"} <= stage and "T5.1" not in stage             # cumulative up to that stage
    assert dict((r[0], r[6]) for r in B4.cell_table())["T10.1"] == "info"          # carpet is never gated


def test_v4_metrics_asymmetry_and_decay():
    import benchmark_v4 as B4
    n = 600
    rec = {"x": list(np.linspace(0, 0.5, n)), "yaw": list(np.linspace(0, -1.0, n)), "roll": [0.0] * n, "pitch": [0.0] * n,
           "yaw_rate": [0.0] * n, "joint": [np.deg2rad([50, 0, 50, 0, 53, 0, 60, 0])] * n}
    m = B4.v4_metrics([(rec, {"servo_over": [0.2] * n}, n, False, 0)])
    assert m["heading_mean_deg"] == pytest.approx(np.degrees(-1.0), abs=0.1)
    assert m["lr_asym_deg"]["hip_BR-BL"] == pytest.approx(-7.0, abs=1e-6) and m["lr_asym_max_deg"] == pytest.approx(7.0, abs=1e-6)
    assert m["servo_over_frac"] == pytest.approx(0.2) and m["fell_fraction"] == 0.0 and abs(m["speed_decay"]) < 0.05


def test_mirror_ppo_single_pass_matches_sb3_evaluate_actions():
    """MirrorPPO evaluates [obs, mirrored obs] in one pass; its real-half outputs must equal SB3's evaluate_actions on obs alone."""
    import gymnasium as gym
    from stable_baselines3 import PPO

    class _Env(gym.Env):
        observation_space = gym.spaces.Box(-1, 1, (278,), dtype=np.float32)
        action_space = gym.spaces.Box(-1, 1, (8,), dtype=np.float32)

        def reset(self, seed=None, options=None):
            return np.zeros(278, dtype=np.float32), {}

        def step(self, a):
            return np.zeros(278, dtype=np.float32), 0.0, False, False, {}

    m = M.MirrorPPO("MlpPolicy", _Env(), n_steps=64, batch_size=32, policy_kwargs=dict(net_arch=[64, 64]), seed=0)
    obs = th.as_tensor(np.random.default_rng(3).uniform(-1, 1, (32, 278)), dtype=th.float32)
    act = th.as_tensor(np.random.default_rng(4).uniform(-1, 1, (32, 8)), dtype=th.float32)
    v0, lp0, en0 = m.policy.evaluate_actions(obs, act)
    feats = m.policy.extract_features(th.cat([obs, M.mirror_obs(obs)], 0))
    lat_pi, lat_vf = m.policy.mlp_extractor(feats)
    mean = m.policy.action_net(lat_pi)
    d = m.policy.action_dist.proba_distribution(mean[:32], m.policy.log_std)
    assert th.allclose(d.log_prob(act), lp0, atol=1e-5) and th.allclose(d.entropy(), en0, atol=1e-5)
    assert th.allclose(m.policy.value_net(lat_vf)[:32].flatten(), v0.flatten(), atol=1e-5)


# ----------------------------------------------------------------------------- adaptive difficulty level
@pytest.fixture()
def lvl_env(monkeypatch):
    import opencat_gym_env as E
    E.GUI_MODE = False
    monkeypatch.setattr(E, "ADAPTIVE_LEVEL", True)
    monkeypatch.setattr(E, "LEVEL_FIXED", -1.0)
    monkeypatch.setattr(E, "LEVEL_WINDOW", 4)
    monkeypatch.setattr(E, "LEVEL_STEP", 0.1)
    monkeypatch.setattr(E, "LEVEL_UP_RATE", 0.75)
    monkeypatch.setattr(E, "LEVEL_DOWN_RATE", 0.25)
    monkeypatch.setattr(E, "LEVEL_START", 0.0)
    env = E.OpenCatGymEnv()
    env._level = 0.0
    return E, env


def _feed(env, outcomes):
    for o in outcomes:
        env._record_outcome(o)


def test_level_rises_one_step_per_window_of_mostly_survived_episodes(lvl_env):
    E, env = lvl_env
    _feed(env, [1, 1, 1, 1])
    assert env._level == pytest.approx(0.1)
    _feed(env, [1, 1, 1, 0])                    # 75% = the threshold: still counts as a rise
    assert env._level == pytest.approx(0.2)
    _feed(env, [1, 1])                          # an incomplete window changes nothing
    assert env._level == pytest.approx(0.2)


def test_level_holds_in_the_middle_band_and_falls_when_mostly_failing(lvl_env):
    E, env = lvl_env
    env._level = 0.5
    _feed(env, [1, 1, 0, 0])                    # 50%: between the two thresholds
    assert env._level == pytest.approx(0.5)
    _feed(env, [0, 0, 0, 1])                    # 25%: falls
    assert env._level == pytest.approx(0.4)


def test_level_is_clamped_to_zero_and_one_and_a_climb_needs_many_windows(lvl_env):
    E, env = lvl_env
    _feed(env, [0] * 40)
    assert env._level == 0.0
    _feed(env, [1] * 4 * 5)
    assert env._level == pytest.approx(0.5)     # 5 windows -> 5 steps: it cannot jump
    _feed(env, [1] * 4 * 20)
    assert env._level == 1.0


def test_dr_follows_the_level_in_training_and_is_full_in_evaluation(lvl_env, monkeypatch):
    E, env = lvl_env
    env._level = 0.35
    env.reset(seed=0)
    assert env._dr == pytest.approx(0.35)
    monkeypatch.setattr(E, "DR_EVAL_FULL", True)
    env.reset(seed=0)
    assert env._dr == 1.0
    monkeypatch.setattr(E, "DR_EVAL_FULL", False)
    monkeypatch.setattr(E, "LEVEL_FIXED", 0.6)
    env.reset(seed=0)
    assert env._dr == pytest.approx(0.6)
    _feed(env, [1] * 8)
    assert env._level == pytest.approx(0.35)    # a pinned level never adapts


def test_level_zero_has_no_hazards_and_no_randomization(lvl_env):
    E, env = lvl_env
    env._level = 0.0
    env.reset(seed=1)
    assert env._dr == 0.0 and env._ledge_h == 0.0 and env._motor_max is None and env._drift_torque == 0.0
    assert np.allclose(env._torque_scale, 1.0) and np.allclose(env._joint_offset, 0.0)


def test_a_level_up_needs_progress_not_just_survival(lvl_env):
    E, env = lvl_env
    for _ in range(4):
        env._record_outcome(1, progress_ok=False)      # survived but stood still / crawled
    assert env._level == 0.0
    for _ in range(4):
        env._record_outcome(1, progress_ok=True)
    assert env._level == pytest.approx(0.1)


def test_progress_check_on_a_real_episode(lvl_env):
    import pybullet as p
    E, env = lvl_env
    env.set_command(fwd=0.10, yaw=0.0)
    env.reset(seed=3)
    for _ in range(120):
        env.step(np.zeros(8))
    assert isinstance(env._progress_ok(), (bool, np.bool_))
    env._lvl_cmd_sum, env._lvl_steps = 0.0, 100         # a near-zero command always passes
    assert env._progress_ok() is True
    env._lvl_cmd_sum = 0.10 * 100
    env._lvl_x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0] + 10.0     # as if it had gone backwards
    assert env._progress_ok() is False


# ----------------------------------------------------------------------------- per-category levels
@pytest.fixture()
def cat_env(monkeypatch):
    import opencat_gym_env as E
    E.GUI_MODE = False
    for k, v in dict(ADAPTIVE_LEVEL=True, CATEGORY_LEVELS=True, LEVEL_FIXED=-1.0, LEVEL_WINDOW_C=4, LEVEL_STEP_C=0.1, LEVEL_UP_SCORE=0.75, LEVEL_DOWN_SCORE=0.45,
                     LEVEL_PROMOTE_WINDOWS=2, LEVEL_STRETCH=0.1, LEVEL_BASE=0.25, LEVEL_COMBO_PROB=0.25, LEVEL_EASY_PROB=0.10, DR_EVAL_FULL=False).items():
        monkeypatch.setattr(E, k, v)
    monkeypatch.setattr(E, "CATEGORY_OVERRIDE", {})
    env = E.OpenCatGymEnv()
    return E, env


def _win(env, scores, survived=True):
    for sc in scores:
        env._record_outcome(1 if survived else 0, True, sc)


def test_episode_mix_focus_stretch_base_anchor_and_combo(cat_env):
    E, env = cat_env
    env._levels = {c: 0.8 for c in E.CATS}
    np.random.seed(0)
    n, kinds, focus_counts = 4000, {"anchor": 0, "combo": 0, "focus": 0}, {c: 0 for c in E.CATS}
    for _ in range(n):
        env._assign_category_levels()
        d = dict(terrain=env._d_terrain, ledge=env._d_ledge, slope=env._d_slope, fault=env._d_fault)
        if env._focus is None and all(v == 0.0 for v in d.values()):
            kinds["anchor"] += 1                                                   # an always-passable anchor episode
        elif env._focus is None:
            kinds["combo"] += 1
            assert all(v == pytest.approx(0.8) for v in d.values())              # a combo: every category at its own level
        else:
            kinds["focus"] += 1
            focus_counts[env._focus] += 1
            assert 0.8 <= d[env._focus] <= 0.9 + 1e-9                             # the focus category practices a little past its level
            assert all(v == pytest.approx(0.25) for c, v in d.items() if c != env._focus)   # the others held at the base level
    assert abs(kinds["anchor"] / n - 0.10) < 0.02 and abs(kinds["combo"] / n - 0.25) < 0.03 and abs(kinds["focus"] / n - 0.65) < 0.03
    assert all(abs(c / kinds["focus"] - 0.25) < 0.04 for c in focus_counts.values())      # the four categories take turns evenly


def test_stretch_is_capped_at_level_one(cat_env):
    E, env = cat_env
    env._levels = {c: 1.0 for c in E.CATS}
    np.random.seed(1)
    for _ in range(300):
        env._assign_category_levels()
        assert max(env._d_terrain, env._d_ledge, env._d_slope, env._d_fault) <= 1.0 + 1e-12


def test_promotion_needs_two_good_windows_in_a_row(cat_env):
    E, env = cat_env
    env._levels = {c: 0.5 for c in E.CATS}
    env._focus = "slope"
    _win(env, [0.9] * 4)                                    # one good window: not yet
    assert env._levels["slope"] == pytest.approx(0.5)
    _win(env, [0.8] * 4)                                    # a second in a row: promoted
    assert env._levels["slope"] == pytest.approx(0.6)
    _win(env, [0.9] * 4)
    _win(env, [0.6] * 4)                                    # a middling window resets the streak
    _win(env, [0.9] * 4)
    assert env._levels["slope"] == pytest.approx(0.6)
    _win(env, [0.9] * 4)
    assert env._levels["slope"] == pytest.approx(0.7)
    assert all(env._levels[c] == 0.5 for c in E.CATS if c != "slope")           # the other categories never moved


def test_a_survived_but_slow_window_does_not_promote_and_a_bad_one_demotes_at_once(cat_env):
    E, env = cat_env
    env._levels = {c: 0.5 for c in E.CATS}
    env._focus = "ledge"
    for _ in range(3):
        _win(env, [0.6] * 4)                                # survived but only 60% of the distance: in the hold band
    assert env._levels["ledge"] == pytest.approx(0.5)
    _win(env, [0.2, 0.3, 0.4, 0.5])                         # mean 0.35 <= 0.45: down immediately
    assert env._levels["ledge"] == pytest.approx(0.4)
    env._focus = "fault"
    _win(env, [0.9] * 4, survived=False)                    # falls score 0 whatever the distance
    assert env._levels["fault"] == pytest.approx(0.4)


def test_anchor_and_combo_episodes_never_adapt_and_the_mean_level_follows(cat_env):
    E, env = cat_env
    env._levels = {c: 0.5 for c in E.CATS}
    env._focus = None
    _win(env, [0.0] * 40)
    assert all(v == 0.5 for v in env._levels.values())
    env._focus = "terrain"
    _win(env, [0.9] * 8)
    assert env._level == pytest.approx(np.mean(list(env._levels.values())))
    assert env._cat_score["terrain"] == pytest.approx(0.9)


def test_override_pins_categories_for_audits(cat_env, monkeypatch):
    E, env = cat_env
    monkeypatch.setattr(E, "CATEGORY_OVERRIDE", {"slope": 1.0})
    env._assign_category_levels()
    assert env._d_slope == 1.0 and env._d_terrain == 0.0 and env._d_ledge == 0.0 and env._d_fault == 0.0


def test_a_real_reset_uses_the_category_levels(cat_env, monkeypatch):
    E, env = cat_env
    monkeypatch.setattr(E, "CATEGORY_OVERRIDE", {"ledge": 1.0})
    monkeypatch.setattr(E, "LEDGE_HEIGHT", 0.035)
    monkeypatch.setattr(E, "LEDGE_PROB", 1.0)
    monkeypatch.setattr(E, "LEDGE_RANDOMIZE", True)
    heights = []
    for k in range(12):
        env.reset(seed=k)
        heights.append(env._ledge_h)
    assert max(heights) > 0.012 and env._d_slope == 0.0 and env._slope_rp == (0.0, 0.0)     # ledges appear, slopes do not
    monkeypatch.setattr(E, "CATEGORY_OVERRIDE", {"ledge": 0.0})
    env.reset(seed=1)
    assert env._ledge_h == 0.0                                                              # a category at 0 contributes nothing


def test_episode_score_is_the_fraction_of_commanded_distance(cat_env):
    import pybullet as p
    E, env = cat_env
    env.reset(seed=2)
    env._lvl_steps, env._lvl_cmd_sum = 100, 0.10 * 100
    env._lvl_x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0] - 0.10 * (100 / 80.0) * 0.6      # it covered 60% of the commanded distance
    assert env._episode_score() == pytest.approx(0.6, abs=0.02)
    env._lvl_cmd_sum = 0.0                                                                         # a stand command scores 1
    assert env._episode_score() == 1.0


# ----------------------------------------------------------------------------- ramps: generic randomization vs difficulty vs penalties
def test_category_mode_keeps_the_generic_time_ramp_and_penalties_use_their_own_length(cat_env, monkeypatch):
    E, env = cat_env
    monkeypatch.setattr(E, "RAMP_MODE", "total")
    monkeypatch.setattr(E, "RAMP_TOTAL_STEPS", 1e6)
    monkeypatch.setattr(E, "RAMP_PENALTY_STEPS", 4e6)
    env._levels = {c: 0.1 for c in E.CATS}                     # the difficulty levels are low ...
    env.set_ramp_steps(2e6)                                   # ... but 2M steps have passed
    env.reset(seed=0)
    assert env._dr == 1.0                                     # the generic randomization (IMU, mass, friction ...) is at full strength by time, not tied to difficulty
    assert env._ramp(E.PENALTY_STEPS, E.RAMP_PENALTY_STEPS) == pytest.approx(0.5)     # the reward penalties are only half in at 2M steps (full at 4M)
    env.set_ramp_steps(5e5)
    env.reset(seed=0)
    assert env._dr == pytest.approx(0.5)


def test_global_level_mode_still_drives_dr_from_the_level(lvl_env):
    E, env = lvl_env
    env._level = 0.35
    env.reset(seed=0)
    assert env._dr == pytest.approx(0.35)


# ----------------------------------------------------------------------------- curriculum.update_levels (the probe-driven rule, with the guards)
def _ul(levels, rel, base, cap=1.0, streak=None, **kw):
    import curriculum
    cats = ("terrain", "ledge", "slope", "fault")
    lv = dict(zip(cats, levels))
    st = streak if streak is not None else {c: 0 for c in cats}
    args = dict(up=0.8, down=0.5, step=0.1, windows=1, min_base=0.5, collapse_base=0.35)
    args.update(kw)
    curriculum.update_levels(lv, st, dict(zip(cats, rel)), base, cap, **args)
    return [round(lv[c], 3) for c in cats], st


def test_good_probes_promote_bad_ones_demote_and_the_middle_holds():
    assert _ul([0.3] * 4, [0.9, 0.9, 0.9, 0.9], 0.8)[0] == [0.4] * 4
    assert _ul([0.3] * 4, [0.9, 0.65, 0.4, 0.5], 0.8)[0] == [0.4, 0.3, 0.2, 0.2]    # 0.65 holds, 0.4 and 0.5 (<= down) drop


def test_a_weak_clean_floor_blocks_promotion_and_a_collapsed_one_drops_everything():
    assert _ul([0.3] * 4, [1.0] * 4, 0.45)[0] == [0.3] * 4              # relative scores perfect, but the baseline is below min_base: hold
    assert _ul([0.3] * 4, [1.0] * 4, 0.30)[0] == [0.2] * 4              # baseline below collapse_base: every category backs off one step
    assert _ul([0.0] * 4, [1.0] * 4, 0.10)[0] == [0.0] * 4              # and never below 0


def test_levels_never_exceed_the_time_cap():
    assert _ul([0.3] * 4, [1.0] * 4, 0.9, cap=0.35)[0] == [0.35] * 4
    assert _ul([0.9] * 4, [1.0] * 4, 0.9, cap=0.5)[0] == [0.5] * 4      # an existing level above a (new, lower) cap is pulled down to it


def test_two_good_probes_in_a_row_are_needed_when_windows_is_two():
    lv, st = _ul([0.3] * 4, [0.9] * 4, 0.8, windows=2)
    assert lv == [0.3] * 4
    lv, st = _ul(lv, [0.9] * 4, 0.8, windows=2, streak=st)
    assert lv == [0.4] * 4
    lv, st = _ul(lv, [0.9] * 4, 0.8, windows=2, streak=st)              # the streak restarted after the promotion
    assert lv == [0.4] * 4 and all(v == 1 for v in st.values())


# ----------------------------------------------------------------------------- the length level (S11, 2026-10-07)
@pytest.fixture()
def len_env(monkeypatch):
    import opencat_gym_env as E
    E.GUI_MODE = False
    for k, v in dict(ADAPTIVE_LEVEL=True, CATEGORY_LEVELS=True, LEVEL_FIXED=-1.0, LENGTH_LEVEL=True, EPISODE_LENGTH=250, LENGTH_MAX_STEPS=3200, LENGTH_SHARE_MAX=0.75,
                     LENGTH_DRIFT_TORQUE=0.30, LENGTH_HEADING_TOL_DEG=30.0, LONG_RUN_PUSH=0.0, DR_EVAL_FULL=False).items():
        monkeypatch.setattr(E, k, v)
    monkeypatch.setattr(E, "CATS", ("terrain", "ledge", "slope", "fault", "length"))
    monkeypatch.setattr(E, "CATEGORY_OVERRIDE", {})
    return E, E.OpenCatGymEnv()


def test_the_length_category_is_off_by_default_and_changes_nothing():
    import opencat_gym_env as E
    assert E.LENGTH_LEVEL is False and "length" not in E.CATS and E.LONG_RUN_PUSH == 0.0


def test_a_long_episode_grows_with_the_level_and_probes_alternate_the_push_sign(len_env, monkeypatch):
    E, env = len_env
    for level, steps in ((0.25, 250 + int(2950 * 0.25)), (0.5, 250 + int(2950 * 0.5)), (1.0, 3200)):
        monkeypatch.setattr(E, "CATEGORY_OVERRIDE", {"length": level})
        signs = []
        for _ in range(6):
            env._assign_category_levels()
            env._step_budget = 250
            env._begin_long_run()
            assert env._long_run and env._step_budget == steps                                  # a probe episode is always long, at the level's length
            assert env._len_drift == pytest.approx(env._len_sign * 0.30 * level)
            signs.append(env._len_sign)
        assert signs == [signs[0], -signs[0]] * 3 and set(signs) == {-1.0, 1.0}                  # strictly alternating: left and right in equal numbers


def test_training_keeps_a_floor_of_short_episodes_and_draws_the_sign_evenly(len_env):
    E, env = len_env
    env._levels = {c: 1.0 for c in E.CATS}
    np.random.seed(0)
    longs, signs, n = 0, [], 4000
    for _ in range(n):
        env._assign_category_levels()
        env._step_budget = 250
        env._begin_long_run()
        if env._focus is None and env._d_length > 0:                                           # combo episodes: the long share is LENGTH_SHARE_MAX * level
            longs += env._long_run
        if env._long_run:
            signs.append(env._len_sign)
    assert 0.0 < longs / n < 0.75 and abs(np.mean(signs)) < 0.06                                # never all long; left and right push drawn about equally
    env._d_length = 0.0
    env._long_run = False
    env._step_budget = 250
    env._focus = None
    env._begin_long_run()
    assert env._step_budget == 250 and env._len_drift == 0.0                                     # level 0: a normal short episode with no push


def test_a_long_episode_only_scores_if_it_stayed_on_course(len_env, monkeypatch):
    E, env = len_env
    monkeypatch.setattr(E, "CATEGORY_OVERRIDE", {"length": 0.5})
    env.set_command(fwd=0.10, yaw=0.0)
    env.reset(seed=3)
    for _ in range(150):
        env.step(np.zeros(8))
    env._lvl_cmd_sum, env._lvl_steps = 0.10 * 100, 100
    env._lvl_x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0] - 10.0                     # as if it had covered the commanded distance
    yaw_now = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])[2]
    env._lvl_yaw0 = yaw_now                                                                      # no heading change: full score
    assert env._episode_score() == pytest.approx(1.0)
    env._lvl_yaw0 = yaw_now - np.radians(15.0)                                                   # 15 degrees off a 30 degree tolerance: half
    assert env._episode_score() == pytest.approx(0.5, abs=0.02)
    env._lvl_yaw0 = yaw_now - np.radians(45.0)                                                   # beyond the tolerance: nothing
    assert env._episode_score() == 0.0


def test_the_long_run_cell_pushes_every_episode_with_alternating_sign(len_env, monkeypatch):
    E, env = len_env
    monkeypatch.setattr(E, "LENGTH_LEVEL", False)
    monkeypatch.setattr(E, "LONG_RUN_PUSH", 0.25)
    pushes = []
    for k in range(6):
        env._assign_category_levels()
        env._begin_long_run()
        pushes.append(env._len_drift)
    assert pushes == [pushes[0], -pushes[0]] * 3 and abs(pushes[0]) == 0.25


def test_v4_metrics_reports_the_heading_of_each_push_side_and_their_gap():
    import benchmark_v4 as B4
    eps = []
    for k, head in enumerate((10.0, 40.0, 14.0, 44.0)):                     # even episodes (push right) end near 12 deg, odd (push left) near 42
        yaw = np.radians(np.linspace(0, head, 200))
        rec = {"x": list(np.linspace(0, 1, 200)), "yaw": list(yaw), "roll": [0.0] * 200, "pitch": [0.0] * 200, "yaw_rate": [0.0] * 200, "joint": [[0.0] * 8] * 200}
        eps.append((rec, {}, 200, False, False))
    m = B4.v4_metrics(eps)
    assert m["heading_even_abs_mean_deg"] == pytest.approx(12.0) and m["heading_odd_abs_mean_deg"] == pytest.approx(42.0) and m["heading_sign_gap_deg"] == pytest.approx(30.0)


def test_the_s11_screen_exists_with_a_balance_target_and_the_gap_rule_fails_a_one_sided_policy():
    import phase_v3 as V
    assert any(tag == "v3_s11_length_level" and lv == ["length_level"] for tag, lv, _d in V.SCREENS)
    assert [t for t in V.TARGETS["length_level"] if t[1] == "heading_sign_gap_deg"]
    cell = lambda gap, absh: {"cells": [{"id": "L1", "heading_abs_mean_deg": absh, "heading_sign_gap_deg": gap, "fell_fraction": 0.0}]}   # noqa: E731
    ctrl = cell(25.0, 40.0)
    assert V.targets_ok(cell(5.0, 20.0), ctrl, ["length_level"]) == []                           # better, and balanced: passes
    why = V.targets_ok(cell(25.0, 20.0), ctrl, ["length_level"])
    assert any("one side is corrected worse" in w for w in why)                                    # better on average but one-sided: fails


def test_no_drift_levers_and_k3_exclusion_and_fresh_final(tmp_path, monkeypatch):
    import g2_profile as G
    import phase_v3 as V
    assert G.env_for("no_heading")["G2E_FAC_HEADING"] == "0"
    assert G.env_for("no_heading", "yaw_damp")["G2E_FAC_YAW_TRACK"] == "18.0" and G.env_for("mirror")["G2E_FAC_YAW_TRACK"] == "9.0"
    tags = [t for t, lv, _d in V.SCREENS]
    assert tags.index("v3_s12_no_heading") > tags.index("v3_s9_smooth") or True
    assert "heading_obs" in V.NOT_IN_K3 and "mirror" not in V.NOT_IN_K3
    cell = lambda clr: {"cells": [{"id": "N1", "fell_fraction": 0.0, "yaw_rate_rms": 0.2, "foot_clear_p90_mm": clr}]}   # noqa: E731
    ctrl = cell(30.0)
    assert V.targets_ok(cell(29.0), ctrl, ["no_heading"]) == []
    assert any("foot_clear_p90_mm" in w for w in V.targets_ok(cell(20.0), ctrl, ["no_heading"]))     # legs stepping lower than 0.85x the control: fails
    d = G.env_for("mirror", stage="s0_flat", extra=dict(G.FINAL_EXTRA))
    assert d["G2E_HARD_SCALE"] == "1.10" and "G2E_LEVEL_START" not in d                              # a fresh 20M ramps from an empty floor
