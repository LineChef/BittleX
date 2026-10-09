"""The V5 training plan (docs/plan-detail/v5-training-plan.md): the V5 course keeps slopes and tilts to 10% of episodes, dealt evenly, never stacks more than two
hazards, gives the hazard-free baseline the same 7.5 s as the hazard episodes, and its sizes are the ladder tops (the old static caps no longer clip them); the
heading-blind policy never sees yaw while its critic does (and the mirror maps cover that); the crossing bonus pays once per field and per ledge edge; the report's
Holm correction and its summary build. Run with the RL venv: pytest test_v5.py."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V5_LEVERS = ["mirror_strong", "frontier", "cmd_forward", "opt_bundle", "privileged_critic", "lr_half", "hazard_long", "v5_course", "kl_limit"]


def _child(code, timeout=900):
    r = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, timeout=timeout)
    assert r.returncode == 0, r.stderr[-2500:]
    return r.stdout


PRELUDE = r"""
import os, sys, collections
sys.path.insert(0, ".")
for k in [k for k in os.environ if k.startswith("G2E_")]:
    del os.environ[k]
import g2_profile
env = g2_profile.env_for_job({"kind": "final", "tag": "t", "fresh": True, "levers": LEVERS})
env["G2E_RECORD_EVERY"] = "0"
g2_profile.set_environ(env)
import numpy as np, pybullet as p
import opencat_gym_env as E
E.GUI_MODE = False
e = E.OpenCatGymEnv(); e.set_ramp_steps(10e6)
"""


def test_v5_course_shares_split_stacking_and_lengths():
    out = _child(PRELUDE.replace("LEVERS", repr(V5_LEVERS)) + r"""
assert E.FR_HAZARDS[:4] == ("sidehill_l", "sidehill_r", "climb", "descent"), E.FR_HAZARDS
assert E.FR_BOUND["sidehill_l"] == 8 and E.FR_BOUND["climb"] == 10 and E.FR_BOUND["ledge_up"] == 0.035 and E.FR_BOUND["ledge_down"] == 0.04
assert E.FR_BACKGROUND_TILT_DEG == 0 and E.FR_MAX_HAZARDS == 2 and E.FR_ANCHOR_LONG
top = np.zeros(12); top[11] = 1.0
e.set_frontier({"w": {h: top.tolist() for h in E.FR_HAZARDS}, "comfort": {h: 11 for h in E.FR_HAZARDS}})
np.random.seed(1)
N = 20000; slope = 0; kinds = collections.Counter(); most = 0
for _ in range(N):
    e._frontier_plan()
    s = [h for h in e._fz if h in E.SLOPE_HAZARDS]
    slope += bool(s); kinds.update(s); most = max(most, len(e._fz))
assert slope / N <= 0.10, slope / N
assert max(kinds.values()) - min(kinds.values()) <= 4, kinds          # the deck deals each kind evenly
assert most <= 2, most
lens = collections.defaultdict(set)
for i in range(40):
    e.reset()
    fz = e._fz or {}
    lens[e._fr_role].add(e._step_budget)
    sl = [h for h in fz if h in E.SLOPE_HAZARDS]
    tilt = np.degrees(max(abs(e._slope_rp[0]), abs(e._slope_rp[1])))
    if sl:
        assert abs(tilt - fz[sl[0]]) < 1e-6 and tilt <= E.FR_BOUND[sl[0]] + 1e-9, (sl, tilt)        # the frontier size is the real size (no silent cap)
        if sl[0] == "sidehill_l": assert e._slope_rp[0] < 0
        if sl[0] == "sidehill_r": assert e._slope_rp[0] > 0
    else:
        assert tilt == 0.0, tilt                                                                      # no background tilt
    if e._ledge_h:
        assert e._ledge_h <= (0.035 if e._ledge_dir > 0 else 0.04) + 1e-9
assert lens["anchor"] == {600}, lens
print("OK", slope / N, dict(kinds))
""")
    assert "OK" in out


def test_heading_blind_hides_yaw_from_the_actor_and_shows_it_to_the_critic():
    out = _child(PRELUDE.replace("LEVERS", repr(V5_LEVERS + ["heading_blind"])) + r"""
import mirror, torch
assert E.HEADING_BLIND and E.PRIV_YAW and E.PRIV_DIM == 24 and mirror.PRIV_DIM == 24
e.set_forced_hazards({})
o, _ = e.reset()
assert o.shape[0] == 278 + 24, o.shape
p.resetBasePositionAndOrientation(e.robot_id, [0, 0, 0.08], p.getQuaternionFromEuler([0, 0, 0.6]))   # turn G2 0.6 rad
for _ in range(20):
    o = e.step(np.zeros(8))[0]
assert abs(p.getEulerFromQuaternion(o[0:4])[2]) < 0.02, o[0:4]                                     # the actor's quaternion carries no yaw
yaw = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(e.robot_id)[1])[2]
assert abs(yaw) > 0.3 and abs(o[-2] - np.sin(yaw)) < 0.02, (o[-2], yaw)                             # the critic's sin(heading error) is the true one
m = mirror.mirror_obs(o[None, :])[0]
assert abs(m[-2] + o[-2]) < 1e-6 and abs(m[-1] - o[-1]) < 1e-6                                      # mirrored heading flips sign, cos stays
print("OK")
""")
    assert "OK" in out


def test_crossing_bonus_pays_once_for_the_field_and_once_for_a_ledge():
    out = _child(PRELUDE.replace("LEVERS", repr(V5_LEVERS + ["cross_bonus"])) + r"""
E.EPISODE_LENGTH = 900
for fz in ({"rubble": 0.25}, {"ledge_down": 0.01}):
    np.random.seed(3)
    e.set_forced_hazards(fz); e.reset(); tot = 0.0; paid = 0
    for t in range(900):
        o, r, te, tr, info = e.step(np.zeros(8)); tot += info["r_cross"]; paid += info["r_cross"] > 0
        if te or tr: break
    n = max(1, len(e._obj_far)) if "rubble" in fz else 1
    assert 0.5 * E.FAC_CROSS <= tot <= E.FAC_CROSS + 1e-6 and paid <= n, (fz, tot, paid, n)      # never more than the field / edge is worth, each piece paid once
print("OK")
""")
    assert "OK" in out


def test_report_holm_and_build():
    sys.path.insert(0, HERE)
    import report_v5 as R
    assert R.holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]

    def cell(cid, falls, n=20, **kw):
        ep = [i < round(falls * n) for i in range(n)]
        d = dict(id=cid, label=cid, fell_fraction=falls, ep_fell=ep, path_speed_mps=0.09, roll_std_deg=3.0, heading_mean_deg=1.0, heading_abs_mean_deg=5.0,
                 lr_asym_max_deg=0.5, pitch_std_deg=1.2, heading_even_abs_mean_deg=3, heading_odd_abs_mean_deg=4, heading_sign_gap_deg=1, n=n)
        d.update(kw)
        return d

    def lad(h, falls):
        import benchmark_v5 as B
        sizes = B.LADDER[h][3]
        cells = [cell(f"Z.{h}.{i + 1}", falls[i], hazard=h, size=s, success=1 - falls[i], past_all=0.5, dist_median_m=0.5) for i, s in enumerate(sizes)]
        return cells
    import benchmark_v5 as B

    def res(f):
        cells = [cell(c, 0.0) for c in ("T1.1", "N1", "N2", "L1")] + [cell("T6.1", f), cell("SL8", f), cell("SR8", f)]
        lc = [cell("Z0", 0.0, hazard=None, size=0.0, success=1.0, dist_median_m=0.7)] + lad("sidehill_l", [0, f, f, f]) + lad("sidehill_r", [0, f, f, f]) + lad("rubble", [0, 0, f, f])
        return dict(cells=cells, mirror_gap=0.03, size_ladder=dict(cells=lc, summary=B.ladder_summary(lc)))
    html = R.build(res(0.05), res(0.6), frontier=None, policy_name="V5")
    for part in ("Verdict", "Per hazard", "What got better", "What got worse", "What did not change", "Symmetry", "All statistics"):
        assert part in html, part
    assert "significant" in html
