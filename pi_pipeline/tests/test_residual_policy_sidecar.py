"""The policy sidecar picks the base gait and its cadence (high-step creep, 2026-10-12): a policy whose `.onnx.json` names `base_ref` and `phase_rate_nom_cmd`
is played on that base at that cadence, exactly as in training; a policy without them stays on wkF at 0.10."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gait"))
import residual_policy as RP  # noqa: E402


def _side(tmp_path, **kw):
    p = tmp_path / "pol.onnx"
    p.write_bytes(b"")
    if kw:
        (tmp_path / "pol.onnx.json").write_text(json.dumps(kw))
    return str(p)


def test_no_sidecar_keeps_wkf_and_nominal_cadence(tmp_path):
    p = _side(tmp_path)
    assert RP.base_ref_path_for(p).endswith("wkf_ref.npy")
    assert RP.sidecar_field(p, "phase_rate_nom_cmd", RP.PHASE_RATE_NOM_CMD) == RP.PHASE_RATE_NOM_CMD


def test_sidecar_names_creep_base_and_cadence(tmp_path):
    p = _side(tmp_path, residual_scale_deg=30, base_ref="creep", phase_rate_nom_cmd=0.035, modes=["hi_step"])
    assert RP.base_ref_path_for(p) == os.path.join(RP._HERE, "creep_ref.npy")
    assert RP.sidecar_field(p, "phase_rate_nom_cmd", RP.PHASE_RATE_NOM_CMD) == 0.035


class _Sess:
    def run(self, _outs, _feed):
        return [np.zeros((1, 8), dtype=np.float32)]


def _policy(nom):
    pol = object.__new__(RP.ResidualGaitPolicy)
    pol._sess, pol._in_name = _Sess(), "obs"
    pol.residual_scale_deg, pol.phase_rate_nom_cmd = 30.0, nom
    pol.WKF_REF = np.zeros((RP.TIME_PHASE_PERIOD, 8))
    pol.STAND_POSE = pol.WKF_REF.mean(axis=0)
    pol._cmd_fwd, pol._cmd_yaw, pol._obs, pol.last_action = 0.0, 0.0, None, None
    return pol


def test_phase_advances_one_frame_per_tick_at_the_sidecar_cadence():
    q, g = [0, 0, 0, 1], [0, 0, 0]
    for nom, cmd in ((0.10, 0.10), (0.035, 0.035)):
        pol = _policy(nom)
        pol.set_command(fwd=cmd)
        pol.reset(np.zeros(8), q, g)
        for _ in range(10):
            pol.step(q, g)
        assert abs(pol._phase - 10.0) < 1e-9
    pol = _policy(0.10)                      # the creep's command on a wkF-cadence policy plays slower (rate 0.35, the floor)
    pol.set_command(fwd=0.035)
    pol.reset(np.zeros(8), q, g)
    for _ in range(10):
        pol.step(q, g)
    assert abs(pol._phase - 3.5) < 1e-9
