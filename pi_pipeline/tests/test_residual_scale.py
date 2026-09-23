"""The residual scale travels with the policy file (2026-09-23). run20m_ppo is
+/-22 deg; every later candidate is +/-30 -- the Pi must apply each policy's
actions at the scale it was trained with, or every correction lands at the
wrong size. export_onnx.py writes `<policy>.onnx.json`; residual_policy reads it.
"""
import json

from pi_pipeline.gait import residual_policy as rp


def test_sidecar_scale_wins(tmp_path):
    onnx = tmp_path / "hw1_20m_ppo.onnx"
    onnx.write_bytes(b"")
    (tmp_path / "hw1_20m_ppo.onnx.json").write_text(json.dumps({"residual_scale_deg": 30.0}))
    assert rp.residual_scale_for(onnx) == 30.0


def test_no_sidecar_falls_back_to_legacy_22(tmp_path):
    onnx = tmp_path / "old.onnx"
    onnx.write_bytes(b"")
    assert rp.residual_scale_for(onnx) == float(rp.RESIDUAL_SCALE_DEG) == 22.0


def test_deployed_policy_declares_its_scale():
    """Whatever DEFAULT_POLICY points at must ship its sidecar (or be the legacy 22)."""
    path = rp.default_policy_path()
    scale = rp.residual_scale_for(path)
    assert scale in (22.0, 30.0)
