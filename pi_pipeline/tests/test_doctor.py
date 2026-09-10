import types

import pytest

from pi_pipeline import doctor


def _fake_settings(**over):
    base = dict(
        anthropic_api_key="sk-ant-xxx",
        vosk_model_path="/nope/vosk",
        piper_model_path="/nope/piper.onnx",
        serial_port="/nope/ttyX",
        serial_baud=115200,
    )
    base.update(over)
    s = types.SimpleNamespace(**base)
    s.api_key_expiry_status = lambda: over.get("_expiry", ("ok", ""))
    return s


@pytest.fixture
def patch_settings(monkeypatch):
    def _apply(**over):
        monkeypatch.setattr("pi_pipeline.config.settings", _fake_settings(**over))
    return _apply


def test_run_returns_named_status_rows(patch_settings):
    patch_settings()
    rows = doctor.run()
    assert rows and all({"name", "status", "detail"} <= r.keys() for r in rows)
    assert all(r["status"] in (doctor.OK, doctor.WARN, doctor.FAIL) for r in rows)


def test_missing_api_key_is_a_hard_fail(patch_settings):
    patch_settings(anthropic_api_key="")
    rows = {r["name"]: r for r in doctor.run()}
    assert rows["ANTHROPIC_API_KEY set"]["status"] == doctor.FAIL


def test_expired_key_is_a_hard_fail(patch_settings):
    patch_settings(_expiry=("expired", "the API key expired 3 days ago"))
    rows = {r["name"]: r for r in doctor.run()}
    assert rows["API key expiry"]["status"] == doctor.FAIL


def test_missing_serial_port_is_only_a_warning(patch_settings):
    patch_settings()
    rows = {r["name"]: r for r in doctor.run()}
    assert rows["serial port exists"]["status"] == doctor.WARN


def test_core_deps_are_detected(patch_settings):
    patch_settings()
    rows = {r["name"]: r for r in doctor.run()}
    assert rows["import anthropic"]["status"] == doctor.OK
    assert rows["import numpy"]["status"] == doctor.OK


def test_main_exit_code_reflects_failures(patch_settings):
    patch_settings(anthropic_api_key="")          # -> a FAIL row
    with pytest.raises(SystemExit) as e:
        doctor.main([])
    assert e.value.code == 1

    patch_settings()                              # clean
    with pytest.raises(SystemExit) as e:
        doctor.main([])
    assert e.value.code == 0
