"""The 2026-10-08 training upgrade (docs/plan-detail/handoff-2026-10-08.md section 12): the frontier curriculum keeps the user's hazard shares and stays inside its bounds,
its update rule finds the frontier and blocks unpassable bins, the privileged critic never leaks into the actor (or the ONNX export), the mirror maps cover the
privileged values, and checkpoints land on the 3M / 5M / 10M names whatever the env count. Run with the RL venv: pytest test_upgrade.py."""
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _child(code, timeout=900):
    r = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, timeout=timeout)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout


FRONTIER_PROBE = r"""
import os, sys, json
sys.path.insert(0, ".")
for k in [k for k in os.environ if k.startswith("G2E_")]:
    del os.environ[k]
import g2_profile
env = g2_profile.next_final_env(); env.update(g2_profile.LEVERS["frontier"]); env["G2E_RECORD_EVERY"] = "0"
g2_profile.set_environ(env)
import numpy as np, pybullet as p
import opencat_gym_env as E
E.GUI_MODE = False
e = E.OpenCatGymEnv(); e.set_ramp_steps(10e6)
# shares, from the plan alone (cheap): 20000 draws
np.random.seed(0)
cnt = {k: 0 for k in ("rubble", "boxes", "slope", "rough", "ledge", "snag", "cutback", "anchor", "focus", "combo")}
N = 20000
for _ in range(N):
    e._frontier_plan()
    z = e._fz
    for h in ("rubble", "boxes", "rough", "snag", "cutback"):
        cnt[h] += h in z
    cnt["slope"] += any(h in z for h in ("sidehill", "climb", "descent"))
    cnt["ledge"] += any(h in z for h in ("ledge_up", "ledge_down"))
    cnt[e._fr_role] = cnt.get(e._fr_role, 0) + 1
print("SHARES " + json.dumps({k: v / N for k, v in cnt.items()}))
# the top bins: every size within its physical bound, the geometry follows the plan, and the episode reports its outcome
top = np.zeros(E.FR_BINS); top[-1] = 1.0
e.set_frontier({"w": {h: top for h in E.FR_HAZARDS}, "comfort": {h: E.FR_BINS - 1 for h in E.FR_HAZARDS}})
bad, reported, seen = [], 0, set()
for k in range(60):
    e.reset(seed=500 + k)
    for h, v in (e._fz or {}).items():
        seen.add(h)
        if not (0 <= v <= E.FR_BOUND[h] + 1e-9):
            bad.append((h, v))
    z = e._fz or {}
    if "sidehill" in z and abs(abs(np.degrees(e._slope_rp[0])) - z["sidehill"]) > 1e-6: bad.append(("sidehill geometry", e._slope_rp))
    if "climb" in z and abs(-np.degrees(e._slope_rp[1]) - z["climb"]) > 1e-6: bad.append(("climb geometry", e._slope_rp))
    if "ledge_up" in z and not (e._ledge_dir == 1 and abs(e._ledge_h - z["ledge_up"]) < 1e-9): bad.append(("ledge geometry", e._ledge_h))
    for t in range(400):
        _o, _r, te, tr, info = e.step(np.zeros(8))
        if te or tr:
            reported += ("fr" in info) or ("fr_anchor" in info)
            break
print("TOP " + json.dumps({"bad": [str(b) for b in bad], "reported": reported, "seen": sorted(seen)}))
"""


def test_frontier_keeps_the_shares_and_the_bounds():
    out = _child(FRONTIER_PROBE)
    import json
    sh = json.loads([l for l in out.splitlines() if l.startswith("SHARES ")][0][7:])
    for k, want in (("rubble", 0.50), ("boxes", 0.30), ("slope", 0.20), ("rough", 0.20), ("ledge", 0.20), ("snag", 0.20), ("cutback", 0.36), ("anchor", 0.10)):
        assert abs(sh[k] - want) < 0.02, (k, sh[k], want)
    top = json.loads([l for l in out.splitlines() if l.startswith("TOP ")][0][4:])
    assert not top["bad"], top["bad"]
    assert top["reported"] >= 25                      # walking anchor and focus episodes report (~60% of episodes); combo, plain and stand episodes do not
    assert {"sidehill", "climb", "descent", "ledge_up", "ledge_down", "rubble", "boxes", "rough", "snag", "cutback"} <= set(top["seen"])


def test_frontier_update_finds_the_frontier_and_blocks_the_impossible():
    sys.path.insert(0, HERE)
    os.environ["G2E_FRONTIER"] = "1"
    import train
    c = train.FrontierCurriculum("zz_test")
    c.num_timesteps = 50_000_000
    c.ramp_offset = 0.0
    for _ in range(400):
        c.anchor.append(1.0)
    h = "ledge_up"
    for b in range(4):
        c.hist[h][b].extend([1.0] * 200)             # bins 0-3 passed
    c.hist[h][4].extend([0.0] * 300)                 # bin 4 never passed after a full window
    for _ in range(10):
        c._update()
    assert c.F[h] == 3 and c.blocked[h] == 4
    w = np.array(c.weights(h))
    assert abs(w.sum() - 1) < 1e-9 and abs(w[4] - c.FLOOR) < 1e-9 and w[5:].sum() == 0 and w[3] > 0.3
    # a hazard with no evidence yet stays at bin 0, weights on bins 0-2
    w0 = np.array(c.weights("rubble"))
    assert c.F["rubble"] == 0 and abs(w0[:3].sum() - 1) < 1e-9
    # a weak clean floor freezes the frontier, a collapsed one lowers it
    c.anchor.clear(); c.anchor.extend([0.3] * 400)
    c._update()
    assert c.F[h] == 2


PRIV_PROBE = r"""
import os, sys
sys.path.insert(0, ".")
for k in [k for k in os.environ if k.startswith("G2E_")]:
    del os.environ[k]
import g2_profile
env = g2_profile.next_final_env(); env.update(g2_profile.LEVERS["privileged_critic"]); env["G2E_RECORD_EVERY"] = "0"
g2_profile.set_environ(env)
import numpy as np, torch
import opencat_gym_env as E
from stable_baselines3.common.vec_env import DummyVecEnv
from mirror import MirrorPPO, mirror_obs, _maps
from priv_policy import PrivCriticPolicy
E.GUI_MODE = False
venv = DummyVecEnv([E.OpenCatGymEnv])
o = venv.reset()
assert o.shape[1] == 278 + E.PRIV_DIM, o.shape
m = MirrorPPO(PrivCriticPolicy, venv, n_steps=64, batch_size=64, n_epochs=1, policy_kwargs=dict(net_arch=[64, 64], priv_dim=E.PRIV_DIM), verbose=0)
m.learn(128)                                         # the mirror loss runs through the separate actor / critic extractors
x = torch.as_tensor(np.random.uniform(-1, 1, (16, o.shape[1])), dtype=torch.float32)
y = x.clone(); y[:, -E.PRIV_DIM:] = torch.as_tensor(np.random.uniform(-1, 1, (16, E.PRIV_DIM)), dtype=torch.float32)
with torch.no_grad():
    a1 = m.policy.get_distribution(x).distribution.mean; a2 = m.policy.get_distribution(y).distribution.mean
    v1 = m.policy.predict_values(x); v2 = m.policy.predict_values(y)
print("ACTOR_SAME", bool(torch.allclose(a1, a2)), "CRITIC_DIFFERS", bool((v1 - v2).abs().max() > 1e-6))
perm, sign = _maps(o.shape[1])
mm = mirror_obs(mirror_obs(np.asarray(o, dtype=np.float64)))
print("MIRROR_INVOLUTION", bool(np.allclose(mm, o)))
m.save("/tmp/zz_priv_policy_test")
import subprocess
r = subprocess.run([sys.executable, "export_onnx.py", "--model", "/tmp/zz_priv_policy_test", "--out", "/tmp/zz_priv_policy_test.onnx"], capture_output=True, text=True)
import onnxruntime as ort
sess = ort.InferenceSession("/tmp/zz_priv_policy_test.onnx")
inp = sess.get_inputs()[0]
out = sess.run(None, {inp.name: x[:, :278].numpy()})[0]
print("EXPORT", inp.shape[1], bool(np.allclose(out, np.clip(a1.numpy(), -1, 1), atol=1e-5)), "OK" in r.stdout)
"""


def test_privileged_critic_never_reaches_the_actor_or_the_export():
    out = _child(PRIV_PROBE)
    line = {l.split()[0]: l.split()[1:] for l in out.splitlines() if l.split() and l.split()[0] in ("ACTOR_SAME", "MIRROR_INVOLUTION", "EXPORT")}
    assert line["ACTOR_SAME"] == ["True", "CRITIC_DIFFERS", "True"], out[-800:]
    assert line["MIRROR_INVOLUTION"] == ["True"]
    assert line["EXPORT"] == ["278", "True", "True"], out[-800:]


def test_checkpoints_land_on_the_gate_names_with_six_envs():
    sys.path.insert(0, HERE)
    import train

    class FakeModel:
        def __init__(self):
            self.saved = []

        def save(self, path):
            self.saved.append(path)
    cb = train.BoundaryCheckpoint(200_000, "zz")
    cb.model = FakeModel()
    for t in range(6, 10_100_000, 6 * 2730):          # 6 envs, one call per rollout-sized stride is enough to cross every boundary
        cb.num_timesteps = t
        cb._on_step()
    names = {os.path.basename(p) for p in cb.model.saved}
    assert {"zz_3000000_steps", "zz_5000000_steps", "zz_10000000_steps"} <= names


CELLS_PROBE = r"""
import os, sys
sys.path.insert(0, ".")
for k in [k for k in os.environ if k.startswith("G2E_")]:
    del os.environ[k]
import g2_profile; g2_profile.set_environ(g2_profile.scoring_env())
import numpy as np, pybullet as p
import opencat_gym_env as E
E.GUI_MODE = False
import benchmark_decathlon as B, benchmark_v4 as V
e = E.OpenCatGymEnv()
bad = []
rows = {r[0]: r for r in V.cell_table(None)}
for cid in ("T1.1", "N1", "T5.2", "T6.1", "T7.2"):
    r = rows[cid]
    B._apply(dict(r[2])); E.EPISODE_LENGTH = r[4] or 250
    for k in range(12):
        np.random.seed(1000 + k); e.reset()
        if abs(p.getBasePositionAndOrientation(e._plane_id)[0][0] - 1.4) < 1e-6:
            bad.append((cid, "rough floor"))
        if E.LEDGE_PROB > 0 and e._ledge_h <= 0:
            bad.append((cid, "no ledge"))
print("CELLS", bad)
"""


def test_benchmark_cells_have_no_stray_training_hazards():
    out = _child(CELLS_PROBE)
    assert "CELLS []" in out, out[-600:]          # 2026-10-08: ~30% of episodes of nearly every cell ran on the training rough floor (and ledge cells then had no ledge)


CMD_BANDS_PROBE = r"""
import os, sys, json
sys.path.insert(0, ".")
for k in [k for k in os.environ if k.startswith("G2E_")]:
    del os.environ[k]
os.environ["G2E_CMD_BANDS"] = "MODE"
import numpy as np
import opencat_gym_env as E
E.GUI_MODE = False
e = E.OpenCatGymEnv()
vals = []
for i in range(600):
    np.random.seed(i); e._sample_command()
    vals.append(float(e._cmd_fwd))
vals = np.array(vals)
print(json.dumps({"fast": float((vals > 0.121).mean()), "back": float((vals < -0.02).mean()), "stand": float(((vals > -0.011) & (vals < 0.021)).mean()),
                  "cruise": float(((vals >= 0.08) & (vals <= 0.12)).mean()), "creep": float(((vals >= 0.04) & (vals <= 0.055)).mean())}))
"""


def test_capped_bands_remove_only_the_unreachable_fast_band():
    import json
    out = {m: json.loads(_child(CMD_BANDS_PROBE.replace("MODE", m)).strip().splitlines()[-1]) for m in ("capped", "forward")}
    assert out["capped"]["fast"] == 0.0 and out["forward"]["fast"] == 0.0
    assert out["forward"]["back"] == 0.0                       # forward: no backward at all
    assert 0.07 < out["capped"]["back"] < 0.20                  # capped keeps backward (about 13%)
    assert 0.40 < out["capped"]["cruise"] < 0.60 and 0.12 < out["capped"]["creep"] < 0.28


def test_path_speed_does_not_lose_a_curving_walk():
    """N2 / L1 'speed decay' is progress along the start direction: a walk that keeps its pace but curves away shows decay. The path metrics must not."""
    import numpy as np
    import benchmark_v4 as B
    steps, hz = 600, B.STEPS_HZ
    t = np.arange(steps) / hz
    ang = np.linspace(0.0, 1.4, steps)                    # the heading turns 80 deg over the episode at a constant pace of 0.08 m/s
    x = np.cumsum(0.08 * np.cos(ang) / hz)
    y = np.cumsum(0.08 * np.sin(ang) / hz)
    rec = {"x": x.tolist(), "y": y.tolist(), "yaw": ang.tolist(), "roll": np.zeros(steps).tolist(), "pitch": np.zeros(steps).tolist(),
           "joint": np.zeros((steps, 8)).tolist(), "yaw_rate": np.zeros(steps).tolist()}
    m = B.v4_metrics([(rec, {}, steps, False, False)] * 2)
    assert abs(m["path_speed_mps"] - 0.08) < 0.004 and abs(m["path_decay"]) < 0.05
    assert m["speed_decay"] > 0.2 and m["speed_mps"] < m["path_speed_mps"]
    assert "pdecay" in B.table({"cells": [dict(m, id="N2")]})
