"""V6 (docs/plan-detail/v6-staged-training-plan.md): the stage mixes set the shares of episodes, the ledge-stage rewards pay and cost what they should, the per-hazard gate and the
chained start exist, and the stage levers assemble. Run with the RL venv: pytest test_v6.py."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = ["mirror_strong", "frontier", "cmd_forward", "opt_bundle", "privileged_critic", "lr_half", "hazard_long", "v5_course", "kl_limit", "cross_bonus", "haz_speed", "haz_posture",
        "heading_blind", "ledge30"]


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


def test_stage_mixes_set_the_shares_and_the_flat_share():
    out = _child(PRELUDE.replace("LEVERS", repr(BASE + ["v6_s2_ledges"])) + r"""
assert E.FR_ANCHOR == 0.20 and E.FR_SHARE["ledge"] == 0.60 and E.FR_SHARE["slope"] == 0.0 and E.FR_SHARE["rough"] == 0.0, (E.FR_ANCHOR, E.FR_SHARE)
top = np.zeros(12); top[5] = 1.0
e.set_frontier({"w": {h: top.tolist() for h in E.FR_HAZARDS}, "comfort": {h: 5 for h in E.FR_HAZARDS}})
np.random.seed(2)
N = 6000; ledge = anchor = slope = 0
for _ in range(N):
    e._frontier_plan()
    ledge += any(h.startswith("ledge") for h in e._fz); anchor += (e._fr_role == "anchor"); slope += any(h in E.SLOPE_HAZARDS for h in e._fz)
assert 0.12 < anchor / N < 0.28, anchor / N          # the stage's flat share
assert ledge / N > 0.45, ledge / N                   # mostly ledges
assert slope == 0
print("ok")
""")
    assert "ok" in out


def test_edge_rewards_stall_penalty_and_lift_bonus():
    out = _child(PRELUDE.replace("LEVERS", repr(BASE + ["v6_s2_ledges"])) + r"""
assert E.FAC_EDGE_STALL == 2.0 and E.FAC_EDGE_LIFT == 1.0
e.reset()
e._ledge_edge, e._ledge_h, e._ledge_dir, e._ledge_passed = 0.30, 0.020, 1, False
e._edge_stall_n = 0
paws = [(0.29, 0.0, 0.0), (0.29, 0.0, 0.0), (0.2, 0.0, 0.0), (0.2, 0.0, 0.0)]
# far from the edge: nothing
assert e._edge_reward(0.0, paws) == 0.0 and e._edge_stall_n == 0
# at the edge, standing still: nothing for the first 40 steps, then -1 per step
p.resetBaseVelocity(e.robot_id, [0, 0, 0], [0, 0, 0])
rs = [e._edge_reward(0.25, paws) for _ in range(60)]
assert rs[:40] == [0.0] * 40 and all(r == -2.0 for r in rs[41:]), rs[35:45]
# a front paw above the ledge top: +20 ONCE per episode (a per-step bonus could be hovered for)
paws_up = [(0.29, 0.0, 0.025), (0.29, 0.0, 0.0), (0.2, 0.0, 0.0), (0.2, 0.0, 0.0)]
e._edge_stall_n = 0
assert e._edge_reward(0.25, paws_up) == 20.0
assert e._edge_reward(0.25, paws_up) == 0.0 and e._edge_lift_paid
e.reset()
assert not e._edge_lift_paid
# once past the ledge nothing is paid
e._ledge_passed = True
assert e._edge_reward(0.25, paws_up) == 0.0
print("ok")
""")
    assert "ok" in out


def test_per_hazard_gate_chain_start_and_stage_levers():
    out = _child(r"""
import os, sys
sys.path.insert(0, ".")
for k in [k for k in os.environ if k.startswith("G2E_")]:
    del os.environ[k]
os.environ["G2E_FR_PASS_H"] = "ledge_up:0.5, ledge_down:0.55"
os.environ["G2E_FR_PASS"] = "0.7"
import re
src = open("train.py").read()
assert "--chain-from" in src and "PASS_H.get(h, self.PASS)" in src
import g2_profile, run_pipeline
for lv in ("v6_s0_flat", "v6_s1_terrain", "v6_s2_ledges", "v6_s3_slopes", "v6_s4_all"):
    assert lv in g2_profile.LEVERS and "G2E_FR_ANCHOR" in g2_profile.LEVERS[lv]
import inspect
assert "chain_from" in inspect.signature(run_pipeline.launch).parameters
import phase_v6 as P6
env = P6.stage_env("s4", "v6_s4_all", last=True)
assert env["G2E_PLATEAU_STOP"] == "1" and "G2E_PLATEAU_STOP" not in P6.stage_env("s1", "v6_s1_terrain")
assert float(env["G2E_LR_FLOOR"]) == 0.0 and P6.PICK_WINDOW == 5
print("ok")
""")
    assert "ok" in out
