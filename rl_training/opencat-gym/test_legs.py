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
