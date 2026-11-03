"""The leg builds (legs_model.py, user 2026-10-31): the wide shoulders and the hinged paws are settings, off by default, chosen per build with G2_BUILD."""
import os
import re
import subprocess
import sys
import textwrap

import pytest

import legs_model as L

HERE = os.path.dirname(os.path.abspath(__file__))
CAD = os.path.join(HERE, "models", "bittle_esp32_cad.urdf")


def _paws_available():
    try:
        return os.path.exists(L.paw_stl("clpaw"))
    except FileNotFoundError:
        return False


def test_stock_legs_by_default(monkeypatch):
    monkeypatch.delenv("G2E_SHOULDER_WIDEN_MM", raising=False)
    monkeypatch.delenv("G2E_PAW", raising=False)
    assert not L.active() and L.pin_friction_default() == 0.0 and L.rim_mur_default() == 0.0
    assert L.build(CAD) == CAD                                     # nothing is built, the stock URDF is loaded as before


def test_the_build_turns_the_legs_on_and_off(monkeypatch):
    import g2_profile as G
    monkeypatch.setenv("G2_PAYLOAD_PROFILE", "arm")
    monkeypatch.delenv("G2_BUILD", raising=False)
    stock = G.scoring_env()
    assert "G2E_PAW" not in stock and "G2E_SHOULDER_WIDEN_MM" not in stock and stock["G2E_BODY_MASS_SCALE"] == "1.0555"
    monkeypatch.setenv("G2_BUILD", "arm_wide_clpaw")
    for env in (G.scoring_env(), G.env_for_job({"kind": "final", "tag": "t", "fresh": True, "levers": []})):
        assert env["G2E_PAW"] == "clpaw" and env["G2E_SHOULDER_WIDEN_MM"] == "5.08" and env["G2E_PAYLOAD_PROFILE"] == "arm"


def test_widening_moves_the_four_leg_mounts_outward():
    base = open(CAD).read()
    wide = L.widen_urdf(base, 5.08)

    def ys(t):
        return {j: float(re.search(r'<joint name="%s"[^>]*>.*?<origin xyz="[-0-9.e]+ ([-0-9.e]+)' % j, t, re.S).group(1)) for j in L.LEG_JOINTS}
    a, b = ys(base), ys(wide)
    for j in L.LEG_JOINTS:
        assert abs(abs(b[j]) - abs(a[j]) - 0.00508) < 1e-6 and (b[j] > 0) == (a[j] > 0)
    assert L.widen_urdf(base, 0) == base


def test_an_unknown_paw_is_refused(monkeypatch):
    monkeypatch.setenv("G2E_PAW", "boots")
    with pytest.raises(ValueError):
        L.paw_name()


@pytest.mark.skipif(not _paws_available(), reason="the paw STL folder (outside the repo) is not on this machine")
def test_the_paw_model_in_the_environment():
    """Four passive plates, never commanded; the stock links found by name; each plate counts as its foot; plate masses are the printed part's, not body-scaled."""
    code = textwrap.dedent('''
        import os, sys
        sys.path.insert(0, ".")
        os.environ["G2_PAYLOAD_PROFILE"] = "arm"; os.environ["G2_BUILD"] = "arm_wide_clpaw"
        import g2_profile
        g2_profile.set_environ(g2_profile.scoring_env())
        import numpy as np, pybullet as p
        import opencat_gym_env as E
        env = E.OpenCatGymEnv(); env.reset(seed=1)
        names = [p.getJointInfo(env.robot_id, j)[12].decode() for j in range(p.getNumJoints(env.robot_id))]
        assert len(env.joint_id) == 8 and len(env._plate_j) == 4, (env.joint_id, env._plate_j)
        assert [names[env._lk(i)] for i in (3, 6, 9, 12)] == ["left_front_paw", "right_front_paw", "right_back_paw", "left_back_paw"]
        assert [names[i] for i in env._paw_plates] == ["left_front_pawplate", "right_front_pawplate", "right_back_pawplate", "left_back_pawplate"]
        assert [env._foot_of(pl) for pl in env._paw_plates] == [env._lk(i) for i in (3, 6, 9, 12)]
        assert all(abs(p.getDynamicsInfo(env.robot_id, pl)[0] - 0.0033) < 0.0005 for pl in env._plate_j)
        for k in range(200):
            env.step(np.zeros(8, dtype=np.float32))
        a = [np.degrees(p.getJointState(env.robot_id, pl)[0]) for pl in env._plate_j]
        assert all(-14.0 <= x <= 31.0 for x in a), a          # the stops are enforced before each physics step: a fraction of a degree past them within one step
        print("ok")
    ''')
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300, cwd=HERE)
    assert out.stdout.strip().endswith("ok"), out.stderr[-2000:]


def test_snag_tops_for_every_build(monkeypatch):
    """Snags (user, 2026-10-31: fixed for all training): every build caps the cord height at its measured top; the ladder takes the same top."""
    import g2_profile as G
    for payload, build, top in (("", "", "1.5"), ("pod", "", "1.5"), ("arm", "", "0.5"), ("arm", "arm_wide_clpaw", "0.5"), ("arm", "arm_wide", "0.5")):
        monkeypatch.setenv("G2_PAYLOAD_PROFILE", payload)
        monkeypatch.setenv("G2_BUILD", build)
        env = G.env_for_job({"kind": "final", "tag": "t", "fresh": True, "levers": []})
        assert f"snag:{top}" in env["G2E_FR_BOUNDS"].split(",") and f"snag:{top}" in env["G2E_V5_BUILD_TOPS"].split(","), (payload, build, env.get("G2E_FR_BOUNDS"))


def test_snags_are_round_cords_by_default(monkeypatch):
    code = textwrap.dedent('''
        import os, sys
        sys.path.insert(0, ".")
        os.environ.pop("G2E_SNAG_ROUND", None)
        import opencat_gym_env as E
        print(E.SNAG_ROUND)
    ''')
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=HERE)
    assert out.stdout.strip().splitlines()[-1] == "True", out.stderr[-1000:]


@pytest.mark.skipif(not _paws_available() or not os.path.exists(os.path.join(HERE, "models", "local", "bittle_dressed_arm.urdf")), reason="the paw STL or the dressed display model is not on this machine")
def test_the_live_viewer_draws_the_runs_legs():
    """g2watchrun (user, 2026-11-01): the run streams its leg build (scene "legs") and the paw angles ("pj"); the viewer builds its display model to match, with the paws, and finds
    the joints by name. Stock legs stream nothing extra."""
    code = textwrap.dedent('''
        import os, sys, json
        sys.path.insert(0, ".")
        os.environ["G2_PAYLOAD_PROFILE"] = "arm"; os.environ["G2_BUILD"] = "arm_wide_clpaw"
        import g2_profile
        g2_profile.set_environ(g2_profile.scoring_env("privileged_critic"))
        import numpy as np, pybullet as p
        import opencat_gym_env as E
        E.GUI_MODE = False
        e = E.OpenCatGymEnv(); e.set_command(fwd=0.1, yaw=0.0)
        e.set_live_slot("legs_test"); e._live_dir = os.path.join(os.environ["LIVE_TMP"])
        os.makedirs(e._live_dir, exist_ok=True); open(os.path.join(e._live_dir, "request"), "w").close()
        e.reset(seed=3)
        for k in range(10): e.step(np.zeros(8, dtype=np.float32))
        sc = json.load(open(os.path.join(e._live_dir, "scene.json")))
        fr = [json.loads(l) for l in open(os.path.join(e._live_dir, sc["frames"]))]
        assert sc["legs"]["paw"] == "clpaw" and sc["legs"]["widen_mm"] == 5.08 and len(sc["legs"]["plate_names"]) == 4
        assert len(fr[-1]["pj"]) == 4
        import watch_live as W
        c = p.connect(p.DIRECT)
        rid, ids = W.build(p, sc, None, None)
        jids, pj = W.joint_ids(p, rid, sc)
        assert len(jids) == 8 and len(pj) == 4
        assert [p.getJointInfo(rid, j)[1].decode() for j in jids] == sc["legs"]["joint_names"]
        print("ok")
    ''')
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300, cwd=HERE, env={**os.environ, "LIVE_TMP": tmp})
    assert "ok" in out.stdout.split(), out.stderr[-2000:]


def test_a_second_20m_gets_its_own_random_stream():
    """The seed-7 20M of 2026-11-01 repeated the seed-42 one exactly: a chained stage ignores G2E_SEED (train.py reads it only for a fresh policy). The extra 20M must carry G2E_CHAIN_SEED."""
    code = textwrap.dedent('''
        import sys
        sys.path.insert(0, ".")
        import phase_arm2 as A
        st = {"chain_extra": {}}
        first = A.stage_env("s4", A.FINAL_LEVER, st, seed="42")
        second = A.stage_env("s4b", A.FINAL_LEVER, st, seed="7", chain_seed="7")
        assert "G2E_CHAIN_SEED" not in first and second["G2E_CHAIN_SEED"] == "7" and second["G2E_SEED"] == "7"
        print("ok")
    ''')
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=HERE)
    assert "ok" in out.stdout.split(), out.stderr[-1500:]


def test_the_real_claw_outline():
    import numpy as np
    import arm_shapes as A
    left, right = np.array(A.jaw_hull("left")), np.array(A.jaw_hull("right"))
    for v, y0 in ((left, A.BOX_Y), (right, -A.BOX_Y)):                              # back in the claw's frame: the hull is relative to its jaw body
        y = v[:, 1] + y0
        assert abs(np.abs(y).max() - A.PLATE_R) < 1e-3                              # 1.9 in across in all (24 mm a side)
        assert abs(v[:, 2].min() - A.BOX_Z_BOTTOM) < 1e-9                           # the same bottom edge as the thin bars: the height off the floor does not change
        assert abs(v[:, 2].max() - (A.BOX_Z_BOTTOM + A.JAW_H)) < 1e-9
    assert np.all(left[:, 1] + A.BOX_Y >= -1e-9) and np.all(right[:, 1] - A.BOX_Y <= 1e-9)    # each half stays on its own side
    import json as _j
    b = _j.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_limits.json")))
    assert b["arm"]["env"]["G2E_CLAW_REAL"] == "1" and b["arm_wide_clpaw"]["env"]["G2E_CLAW_REAL"] == "1"      # on in both arm builds
    assert "G2E_CLAW_REAL" not in b["pod"].get("env", {}) and "G2E_CLAW_REAL" not in b["_default"].get("env", {})     # and nowhere else


def test_the_arm_wide_build_has_wide_shoulders_and_stock_feet(monkeypatch):
    """ARMW (user, 2026-11-03): the 0.2 in wide shoulders on the stock feet: the shoulder setting is on, no paw is."""
    import g2_profile as G
    monkeypatch.setenv("G2_PAYLOAD_PROFILE", "arm")
    monkeypatch.setenv("G2_BUILD", "arm_wide")
    env = G.scoring_env()
    assert env["G2E_SHOULDER_WIDEN_MM"] == "5.08" and env.get("G2E_PAW", "none") == "none"
