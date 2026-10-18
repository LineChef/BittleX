"""Attachments (none / head / arm) and the gait saved for each. The first tests pin the guarantee: attachment `none` is exactly the
behaviour from before attachments existed."""
import json
import os

import pytest

from pi_pipeline import attachments as A
from pi_pipeline.gait import heading_hold as H
from pi_pipeline.gait import residual_policy as R
from pi_pipeline.voice import skills as S


def _legacy_policy_path():
    """residual_policy.default_policy_path as it was written before attachments existed."""
    here = os.path.dirname(os.path.abspath(R.__file__))
    train = os.path.normpath(os.path.join(here, "..", "..", "rl_training", "opencat-gym", "trained", R.DEFAULT_POLICY))
    return next((p for p in (os.path.join(here, R.DEFAULT_POLICY), train) if os.path.exists(p)), os.path.join(here, R.DEFAULT_POLICY))


# ------------------------------------------------------------------------------------------------- none = the old behaviour, exactly

def test_the_default_is_none():
    assert A.current() == "none"


def test_none_keeps_the_legacy_policy_trim_and_skills(monkeypatch):
    monkeypatch.delenv("G2_FOOT_TRIM", raising=False)
    assert R.default_policy_path() == _legacy_policy_path()
    for name, trim in H.DEFAULT_TRIMS.items():
        assert H.default_foot_trim(name) == H.parse_foot_trims(trim)
    assert not set(A._ARM_SKILLS) & set(S.SKILLS)


def test_none_sets_only_the_voice_module_language_at_start_up(monkeypatch):
    monkeypatch.setattr(A.time, "sleep", lambda _s: None)
    class Link:
        sent = []

        def send(self, cmd, **kw):
            self.sent.append(cmd)
            return "Bittle X"
    lk = Link()
    assert A.startup_check(lk) is None and lk.sent == ["XAc", "XAa"]            # no `?`, no skills, no firmware question


def test_none_never_imports_the_head_tool_server():
    import subprocess
    import sys
    code = ("import sys; import pi_pipeline.gait.residual_policy as R, pi_pipeline.voice.skills, pi_pipeline.attachments as A; R.default_policy_path(); "
            "A.startup_check(None); print('pi_pipeline.head' in sys.modules)")
    env = {k: v for k, v in os.environ.items() if k != "G2_ATTACHMENT"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=os.path.join(os.path.dirname(R.__file__), "..", ".."))
    assert out.stdout.strip().splitlines()[-1] == "False", out.stderr[-400:]


# ------------------------------------------------------------------------------------------------- choosing the attachment

def test_env_beats_the_state_file_and_unknown_names_are_none(monkeypatch):
    A.use("arm")
    assert A.current() == "arm"
    monkeypatch.setenv("G2_ATTACHMENT", "head")
    assert A.current() == "head"
    monkeypatch.setenv("G2_ATTACHMENT", "jetpack")
    assert A.current() == "none"
    with pytest.raises(ValueError):
        A.use("jetpack")


# ------------------------------------------------------------------------------------------------- the saved gaits

@pytest.fixture
def policies(tmp_path, monkeypatch):
    """Three fake policies with sidecars; _policy_file finds them in tmp_path."""
    def make(name, payload):
        p = tmp_path / name
        p.write_bytes(b"onnx")
        p.with_name(name + ".json").write_text(json.dumps({"residual_scale_deg": 30, **({"payload_profile": payload} if payload else {})}))
        return str(p)
    paths = {"V7.onnx": make("V7.onnx", "pod"), "V6.onnx": make("V6.onnx", "case2"), "OLD.onnx": make("OLD.onnx", None)}
    monkeypatch.setattr(A, "_policy_file", lambda name: paths.get(name))
    return paths


def _prof(current, *history, payload="pod"):
    return {"head": {"payload_profile": payload, "current": {"policy": current, "trim": "fl=-0.3"} if current else None,
                     "history": [{"policy": h, "trim": None} for h in history]}}


def test_head_uses_its_saved_policy_and_trim(policies, monkeypatch):
    g = A.gait_for("head", _prof("V7.onnx"))
    assert g.path == policies["V7.onnx"] and g.trim == "fl=-0.3" and "saved current" in g.why


def test_a_policy_trained_on_another_payload_is_skipped(policies):
    g = A.gait_for("head", _prof("V6.onnx", "V7.onnx"))
    assert g.path == policies["V7.onnx"] and "last-known-good" in g.why and "case2" in g.why


def test_a_missing_file_falls_back_to_the_last_known_good(policies):
    g = A.gait_for("head", _prof("GONE.onnx", "V7.onnx"))
    assert g.path == policies["V7.onnx"] and "file missing" in g.why


def test_nothing_usable_means_the_legacy_policy(policies):
    g = A.gait_for("head", _prof("V6.onnx"))
    assert g.path is None and "legacy DEFAULT_POLICY" in g.why
    assert A.gait_for("arm", {"arm": {"current": None, "history": []}}).path is None


def test_a_policy_without_a_recorded_payload_is_allowed_and_flagged(policies):
    g = A.gait_for("head", _prof("OLD.onnx"))
    assert g.path == policies["OLD.onnx"] and "not recorded" in g.why


def test_default_policy_path_and_trim_follow_the_attachment(policies, monkeypatch, tmp_path):
    prof = tmp_path / "profiles.json"
    prof.write_text(json.dumps(_prof("V7.onnx")))
    monkeypatch.setattr(A, "PROFILES_PATH", str(prof))
    monkeypatch.setenv("G2_ATTACHMENT", "head")
    monkeypatch.delenv("G2_FOOT_TRIM", raising=False)
    assert R.default_policy_path() == policies["V7.onnx"]
    assert H.default_foot_trim(policies["V7.onnx"]) == H.parse_foot_trims("fl=-0.3")
    monkeypatch.setenv("G2_FOOT_TRIM", "off")                 # the explicit override still wins
    assert H.default_foot_trim(policies["V7.onnx"]) is None


def test_none_runs_its_own_saved_gait_once_one_is_saved(policies, monkeypatch, tmp_path):
    prof = tmp_path / "profiles.json"
    A.register("none", "OLD.onnx", trim="fl=-0.1", payload_profile="pod_none", path=str(prof))
    monkeypatch.setattr(A, "PROFILES_PATH", str(prof))
    monkeypatch.delenv("G2_FOOT_TRIM", raising=False)
    assert A.current() == "none"
    assert R.default_policy_path() == policies["OLD.onnx"]
    assert H.default_foot_trim(policies["OLD.onnx"]) == H.parse_foot_trims("fl=-0.1")
    g = A.gait_for("none", {"none": {"payload_profile": "pod_none", "current": {"policy": "V7.onnx"}, "history": []}})
    assert g.path is None                                     # a head-trained (pod) policy is refused for no attachment


def test_register_keeps_the_previous_one_as_last_known_good(tmp_path):
    p = str(tmp_path / "profiles.json")
    A.register("head", "V6.onnx", payload_profile="pod", path=p)
    prof = A.register("head", "trained/V7.onnx", trim="fl=-0.2", path=p)
    assert prof["current"]["policy"] == "V7.onnx" and prof["current"]["trim"] == "fl=-0.2"
    assert [e["policy"] for e in prof["history"]] == ["V6.onnx"] and prof["payload_profile"] == "pod"
    with pytest.raises(ValueError):
        A.register("jetpack", "V7.onnx", path=p)


def test_the_shipped_profiles_file_is_valid():
    data = A.load_profiles()
    assert set(data) == set(A.ATTACHMENTS)
    assert data["head"]["payload_profile"] == "pod"
    assert not data["none"]["current"] and not data["none"]["history"]     # until a no-attachment gait is saved, none = the legacy behaviour


# ------------------------------------------------------------------------------------------------- firmware and skills

def test_firmware_check():
    assert A.check_firmware("Bittle X+Arm\nB10_260101", "arm")[0]
    assert not A.check_firmware("Bittle X\nB10_260101", "arm")[0]        # the plain build is not the arm build
    assert A.check_firmware("Bittle X\n", "head")[0]
    assert not A.check_firmware("", "arm")[0]
    assert A.check_firmware("anything", "none")[0]


def test_arm_skills_come_and_go_with_the_firmware(monkeypatch):
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    S._add_attachment_skills()
    try:
        assert S.serial_command("pick_up") == "kpickF"

        class Plain:
            def send(self, cmd, **kw):
                return "Bittle X\nB10_260101"
        assert A.startup_check(Plain()) is False
        assert "pick_up" not in S.SKILLS
    finally:
        S.remove_attachment_skills()
    assert not set(A._ARM_SKILLS) & set(S.SKILLS)


def test_the_cli(capsys):
    from pi_pipeline.attachments.__main__ import main
    assert main(["use", "head"]) == 0 and A.current() == "head"
    assert "attachment: head" in capsys.readouterr().out
    assert main(["list"]) == 0 and "arm:" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------- voice module language

def test_the_head_profile_sets_the_voice_module_to_english_at_start_up(monkeypatch):
    monkeypatch.setattr(A.time, "sleep", lambda _s: None)
    sent = []
    class Link:
        def send(self, cmd, **kw):
            sent.append(cmd)
            return "Bittle X"
    A.use("head")
    A.startup_check(Link())
    assert sent[:2] == ["XAc", "XAa"] and "XAd" not in sent and "Xa" not in sent


def test_every_profile_says_english_and_a_missing_profile_still_does(monkeypatch):
    for name in ("none", "head", "arm"):
        assert A.voice_module_language(name) == "english"
    assert A.voice_module_language("head", {}) == "english"                       # the profile file is missing or unreadable
    assert A.voice_module_language("head", {"head": {"voice_module_language": "  "}}) == "english"
    assert A.voice_module_language("head", {"head": {"voice_module_language": "off"}}) is None
    monkeypatch.setattr(A.time, "sleep", lambda _s: None)
    sent = []
    class Link:
        def send(self, cmd, **kw):
            sent.append(cmd)
            return "Bittle X"
    assert A.apply_voice_module_language(None, "head") is False
    assert A.apply_voice_module_language(Link(), "arm") is True and sent == ["XAc", "XAa"]


def test_an_unsupported_language_or_a_failing_link_sends_nothing_and_never_raises(monkeypatch):
    monkeypatch.setattr(A.time, "sleep", lambda _s: None)
    monkeypatch.setattr(A, "load_profiles", lambda path=None: {"head": {"voice_module_language": "klingon"}})
    class Link:
        def send(self, cmd, **kw):
            raise OSError("gone")
    assert A.apply_voice_module_language(Link(), "head") is False
    monkeypatch.setattr(A, "load_profiles", lambda path=None: {"head": {"voice_module_language": "english"}})
    assert A.apply_voice_module_language(Link(), "head") is False
