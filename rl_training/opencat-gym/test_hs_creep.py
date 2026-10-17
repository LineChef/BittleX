"""The high-step creep (2026-10-12, docs/archive/plan-detail/high-step-creep-training-plan.md): the base gait generator, the env knobs (off = unchanged), step-ups only, and the
new ledge rewards. Run with the RL venv."""
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "reference_gait"))
import build_creep_reference as BC  # noqa: E402


def test_creep_generator_shape_symmetry_and_three_feet_down():
    for kw in ({}, {"lean": 8, "sway": 18, "A": 14}, {"sway_f": 8}):
        ref = BC.build(**kw)
        assert ref.shape == (100, 8)
        assert BC.mirror_error_deg(ref) < 1e-6                      # mirrored = itself half a cycle later (what mirror.py assumes)
    raw = dict(BC.DEFAULTS)
    duty = raw["duty"]
    for i in range(100):                                             # never more than one leg in the air (three feet down)
        assert sum(((i / 100 + o) % 1.0) >= duty for o in BC.OFFS) <= 1


def _probe(code, env):
    full = {k: v for k, v in os.environ.items() if not k.startswith("G2E_")}
    full.update(env)
    r = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=full, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("{")][-1])


KNOBS = r"""
import json, opencat_gym_env as E
print(json.dumps(dict(nom=E.PHASE_RATE_NOM_CMD, fp=E.FAC_FOOT_PHASE, gs=E.FAC_GAIT_SYMMETRY, up=E.FAC_UPRIGHT, st=E.FAC_STABILITY, hf=E.HEIGHT_FLOOR, pf=E.PAW_Z_FRONT,
    pr=E.PAW_Z_REAR, one=E.CLEAR_ONE_SIDED, cl=E.FAC_CLEARANCE, lu=E.FR_LEDGE_UP_ONLY, au=E.FAC_ALL_UP, fh=E.FAC_FACE_HIT, rp=E.FAC_REAR_POSTURE, bands=E.CMD_BANDS)))
"""


def test_knobs_default_off_and_hs_creep_sets_them():
    d = _probe(KNOBS, {})
    assert d == dict(nom=0.10, fp=1.5, gs=3.5, up=3.0, st=0.1, hf=0.0, pf=0.0, pr=0.0, one=False, cl=0.1, lu=False, au=0.0, fh=0.0, rp=0.0, bands=""), d
    sys.path.insert(0, HERE)
    import g2_profile
    d = _probe(KNOBS, dict(g2_profile.LEVERS["hs_creep"]))
    assert d["nom"] == 0.035 and d["fp"] == 0.0 and d["gs"] == 0.0 and d["lu"] is True and d["one"] is True and d["bands"] == "creep" and d["au"] == 150.0, d


LEDGES = r"""
import json, os, sys
sys.path.insert(0, ".")
import numpy as np, opencat_gym_env as E
E.GUI_MODE = False
e = E.OpenCatGymEnv()
dirs = []
for k in range(300):
    np.random.seed(k)
    e._frontier_plan()
    dirs += [h for h in e._fz if h.startswith("ledge")]
cmds = []
for k in range(400):
    np.random.seed(k); e._sample_command(); cmds.append(e._cmd_fwd)
print(json.dumps(dict(dirs=sorted(set(dirs)), n=len(dirs), cmd_max=max(cmds), cmd_min=min(cmds))))
"""


def test_step_ups_only_and_creep_commands():
    env = {"G2E_FRONTIER": "1", "G2E_FR_ANCHOR": "0.1", "G2E_FR_SHARE_SET": "ledge:0.6", "G2E_FR_LEDGE_UP_ONLY": "1", "G2E_CMD_BANDS": "creep"}
    d = _probe(LEDGES, env)
    assert d["dirs"] == ["ledge_up"] and d["n"] > 50, d
    assert d["cmd_max"] <= 0.040 + 1e-9 and d["cmd_min"] >= -0.01 - 1e-9, d


REWARD = r"""
import json, os, sys
sys.path.insert(0, ".")
import numpy as np, pybullet as p, opencat_gym_env as E
E.GUI_MODE = False
e = E.OpenCatGymEnv()
e.set_forced_hazards({"ledge_up": 0.012}); e.set_command(fwd=0.035, yaw=0.0)
e.reset(seed=1)
rid, lid, h = e.robot_id, e._ledge_id, e._ledge_h
# move G2 onto the block top, all four paws on it: the bonus is paid once, and only once
p.resetBasePositionAndOrientation(rid, [e._ledge_edge + 0.20, 0, 0.08 + h], [0, 0, 0, 1])
for _ in range(60):
    p.stepSimulation()
r1 = e._hs_ledge_reward(e._ledge_edge + 0.20); r2 = e._hs_ledge_reward(e._ledge_edge + 0.20)
# a fresh episode with G2 pressed against the face: the face cost
e.reset(seed=2)
p.resetBasePositionAndOrientation(rid, [e._ledge_edge - 0.075, 0, 0.08], [0, 0, 0, 1])
hits = 0
for _ in range(80):
    p.stepSimulation()
    hits += e._hs_ledge_reward(e._ledge_edge - 0.075) < 0
print(json.dumps(dict(r1=r1, r2=r2, on_top=len(e._hs_on_top), hits=hits)))
"""


def test_all_up_paid_once():
    d = _probe(REWARD, {"G2E_FAC_ALL_UP": "150", "G2E_FAC_FACE_HIT": "0.5"})
    assert d["r1"] == 150.0 and d["r2"] == 0.0, d


STALL = r"""
import json, os, sys
sys.path.insert(0, ".")
import numpy as np, pybullet as p, opencat_gym_env as E
E.GUI_MODE = False
e = E.OpenCatGymEnv()
e.set_forced_hazards({"ledge_up": 0.012}); e.set_command(fwd=0.035, yaw=0.0)
e.reset(seed=3)
# the creep rocks: instantaneous speed alternates 0.05 / 0.0 while the body goes nowhere. The old speed test (under 2 cm/s for 40 CONSECUTIVE steps) never fires on that.
paws = [(0.0, 0.0, 0.0)] * 4
rs = []
for k in range(260):
    p.resetBaseVelocity(e.robot_id, [0.05 if k % 2 else 0.0, 0, 0], [0, 0, 0])
    rs.append(e._edge_reward(e._ledge_edge + 0.05, paws))
# paw bonus: a rear paw first standing on top pays FAC_PAW_UP once, a front paw 0.3x
e.reset(seed=4)
rid, lid, h = e.robot_id, e._ledge_id, e._ledge_h
p.resetBasePositionAndOrientation(rid, [e._ledge_edge + 0.20, 0, 0.08 + h], [0, 0, 0, 1])
for _ in range(60):
    p.stepSimulation()
r1 = e._hs_ledge_reward(e._ledge_edge + 0.20)
print(json.dumps(dict(early=min(rs[:100]), late=min(rs[200:]), r1=r1, n=len(e._hs_on_top))))
"""


def test_windowed_edge_stall_fires_for_a_rocking_creep_and_paws_are_paid():
    d = _probe(STALL, {"G2E_FAC_EDGE_STALL": "2.0", "G2E_EDGE_STALL_WINDOW": "120", "G2E_FAC_ALL_UP": "150", "G2E_FAC_PAW_UP": "100", "G2E_FAC_FACE_HIT": "0.15"})
    assert d["early"] == 0.0 and d["late"] < -2.0, d                      # nothing for the first 1.5 s, then the cost, growing
    assert d["r1"] == 2 * 100.0 + 2 * 30.0 + 150.0 and d["n"] == 4, d      # 2 rear x 100, 2 front x 30, all four 150
    old = _probe(STALL, {"G2E_FAC_EDGE_STALL": "2.0"})
    assert old["late"] == 0.0, old                                          # the V6 test really never fired on this motion


MIDSWING = r"""
import json, sys
sys.path.insert(0, ".")
import numpy as np, opencat_gym_env as E
E.GUI_MODE = False
ref = E.WKF_REF
n = [0, 0, 0, 0]; multi = 0
for i in range(100):
    f = E.OpenCatGymEnv._mid_swing(ref[i])
    multi += sum(f) > 1
    for k in range(4): n[k] += f[k]
print(json.dumps(dict(n=n, multi=multi)))
"""


def test_mid_swing_flags_each_leg_for_part_of_its_swing_and_never_two_at_once():
    d = _probe(MIDSWING, {"G2E_SKILL_REF": "creep"})
    assert all(8 <= x <= 25 for x in d["n"]) and d["multi"] == 0, d      # each leg flagged for part of its 20-frame swing; three feet stay down


REPORTED = r"""
import json, sys
sys.path.insert(0, ".")
import numpy as np, opencat_gym_env as E
E.GUI_MODE = False
e = E.OpenCatGymEnv()
out = {}
for cmd in (0.02, 0.032, 0.038):
    e.set_forced_hazards({}); e.set_command(fwd=cmd, yaw=0.0); e.reset(seed=2)
    for _ in range(60): e.step(np.zeros(8))
    info = {}
    e._fr_report(False, info)
    out[str(cmd)] = "fr_anchor" in info
print(json.dumps(out))
"""


def test_creep_episodes_are_reported_to_the_frontier_but_stands_are_not():
    d = _probe(REPORTED, {"G2E_CMD_BANDS": "creep"})
    assert d == {"0.02": False, "0.032": True, "0.038": True}, d      # at the old 0.04 threshold no creep command was ever reported
    old = _probe(REPORTED, {})
    assert old == {"0.02": False, "0.032": False, "0.038": False}, old
