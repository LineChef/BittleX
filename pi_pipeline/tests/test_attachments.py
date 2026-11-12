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
    assert not A.check_firmware("Bittle X+Arm\nB10_260101", "head")[0]   # the arm build shifts every posture: not for the AI head
    assert not A.check_firmware("", "arm")[0]
    assert A.check_firmware("anything", "none")[0]


def test_arm_skills_come_and_go_with_the_firmware(monkeypatch, tmp_path):
    prof = tmp_path / "profiles.json"
    prof.write_text(json.dumps({"arm": {"payload_profile": "arm", "current": None, "history": [], "skills": True}}))
    monkeypatch.setattr(A, "PROFILES_PATH", str(prof))
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


# ------------------------------------------------------------------------------------------------- the arm's first hardware round: switches off

def test_switches_are_on_unless_a_profile_says_false():
    assert all(A.flag(k, "none") and A.flag(k, "head") for k in ("easing", "gyro_balance", "gait_switching", "skills"))
    assert A.flag("easing", "arm", {"arm": {"easing": False}}) is False
    assert A.flag("easing", "arm", {"arm": {}}) is True


def test_the_shipped_arm_profile_runs_without_easing_gyro_gait_switching_or_fall_recovery():
    data = A.load_profiles()["arm"]
    assert data["payload_profile"] == "arm"
    # (2026-11-08: the gyro balance was on for a few hours and the board started its own `rc` / `up` self-right during a claw look and flipped him: it is off again; G2_GYRO_BALANCE=1 turns it on for one run)
    assert not any(A.flag(k, "arm") for k in ("easing", "gyro_balance", "gait_switching", "fall_recovery"))
    assert A.flag("skills", "arm")                                              # the claw's voice skills are on (user, 2026-11-02)


def test_the_arm_puts_all_its_claw_skills_into_the_conversation(monkeypatch):
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    S._add_attachment_skills()
    try:
        assert set(A._ARM_SKILLS) <= set(S.SKILLS) and len(A._ARM_SKILLS) == 15
        assert S.serial_command("pick_up") == "kpickF" and S.serial_command("clap") == "kclap" and S.serial_command("hunt") == "khunt"
    finally:
        S.remove_attachment_skills()


def test_no_easing_with_the_arm(monkeypatch):
    from pi_pipeline.gait import standup
    from pi_pipeline.link import transitions
    monkeypatch.delenv("G2_STAND_RAMP_S", raising=False)
    monkeypatch.delenv("G2_TRANSITION_RAMP_S", raising=False)
    assert standup.ramp_seconds() == standup.DEFAULT_RAMP_S and transitions.max_seconds() > 0
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    assert standup.ramp_seconds() == 0.0                                                                 # easing (the stand-up ramp, smoothing a skill's own motion): off for the arm
    assert transitions.max_seconds() > 0                                                                 # blending (pose to pose) is back on for the arm (user, 2026-10-25)
    sent = []
    assert standup.blend_to_balance(sent.append, sleep=lambda s: None, last_motion_command="i8 40 9 40") is False and not sent


def _arm_gyro_off(monkeypatch):
    """The arm profile as it shipped until 2026-11-08 (gyro balance off, so every `gB` becomes `gb` and each skill is followed by `gb`): these tests pin that mechanism."""
    import copy
    real = A.load_profiles
    def patched(*a, **k):
        d = copy.deepcopy(real(*a, **k))
        d["arm"]["gyro_balance"] = False
        return d
    monkeypatch.setattr(A, "load_profiles", patched)


def test_the_arm_turns_every_gB_into_gb(monkeypatch):
    _arm_gyro_off(monkeypatch)
    from pi_pipeline.link.serial_link import SerialLink

    class FakeSerial:
        def __init__(self):
            self.out = []
            self.is_open = True
        def write(self, b):
            self.out.append(b.decode().strip())
        def flush(self):
            pass
    lk = SerialLink("/dev/null")
    lk._ser = FakeSerial()
    monkeypatch.setattr(SerialLink, "is_connected", property(lambda self: True))
    lk.send("gB", read_reply=False, settle=0.0)
    assert lk._ser.out == ["gB"]
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    lk.send("gB", read_reply=False, settle=0.0)
    assert lk._ser.out[-1] == "gb"


def test_startup_turns_the_gyro_off_for_the_arm(monkeypatch):
    _arm_gyro_off(monkeypatch)
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    sent = []

    class Arm:
        def send(self, cmd, **kw):
            sent.append(cmd)
            return "Bittle X+Arm\nB10_260101" if cmd == "?" else ""
    assert A.startup_check(Arm()) is True
    assert sent[-1] == "gb"


def test_the_arm_holds_the_normal_gait(monkeypatch, tmp_path):
    from pi_pipeline.gait import gait_mode as G
    p = str(tmp_path / "gait_mode.json")
    G.set_mode("hi_step", p)
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    assert G.current(p) == "normal" and G.blend(p)[:2] == ("normal", "normal")
    gait, said = G.request("high step", path=p)
    assert gait is None and "arm" in said                 # refused (the losing horn), with the reason
    assert G.request("walk normally", path=p)[0] == "normal"
    assert G.follow_floor("carpet", p) == "normal"
    assert "fixed" in G.claude_hint()
    monkeypatch.delenv("G2_ATTACHMENT")
    assert G.current(p) == "hi_step"                       # the head and no attachment are unchanged


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


def test_the_voice_module_replies_are_read_so_the_firmware_check_sees_the_real_banner(monkeypatch):
    monkeypatch.setattr(A.time, "sleep", lambda _s: None)
    class Link:
        def __init__(self):
            self.pending = []

        def send(self, cmd, *, read_reply=True, **kw):
            if cmd.startswith("X"):
                self.pending.append("X")                      # the board's stray answer to an X command
            elif cmd == "?":
                self.pending.append("Bittle X")
            if not read_reply:
                return ""
            return self.pending.pop(0)
    A.use("head")
    assert A.startup_check(Link()) is True


def test_a_trim_measured_on_the_current_floor_wins_on_that_floor_only(policies, monkeypatch, tmp_path):
    prof = tmp_path / "profiles.json"
    prof.write_text(json.dumps(_prof("V7.onnx")))
    monkeypatch.setattr(A, "PROFILES_PATH", str(prof))
    monkeypatch.setenv("G2_ATTACHMENT", "head")
    monkeypatch.delenv("G2_FOOT_TRIM", raising=False)
    A.set_floor_trim("head", "Tile", "fl=-0.1", path=str(prof))
    assert A.load_profiles(str(prof))["head"]["current"]["trim_by_floor"] == {"tile": "fl=-0.1"}
    v7 = policies["V7.onnx"]
    assert H.default_foot_trim(v7, floor="tile") == H.parse_foot_trims("fl=-0.1")
    assert H.default_foot_trim(v7, floor="hardwood") == H.parse_foot_trims("fl=-0.3")      # no hardwood entry: the general trim
    assert H.default_foot_trim(v7, floor=None) == H.parse_foot_trims("fl=-0.3")
    monkeypatch.setattr(H, "current_floor", lambda: "tile")
    assert H.default_foot_trim(v7) == H.parse_foot_trims("fl=-0.1")                        # "auto" reads the floor label
    A.set_floor_trim("head", "tile", None, path=str(prof))
    assert H.default_foot_trim(v7, floor="tile") == H.parse_foot_trims("fl=-0.3")


def test_a_stale_or_unknown_floor_label_is_not_used(monkeypatch):
    from pi_pipeline.telemetry import autolog
    monkeypatch.setattr(autolog, "get_surface_info", lambda: ("tile", 30.0))
    assert H.current_floor() is None
    monkeypatch.setattr(autolog, "get_surface_info", lambda: ("tile", 1.0))
    assert H.current_floor() == "tile"
    monkeypatch.setattr(autolog, "get_surface_info", lambda: ("unknown", 0.1))
    assert H.current_floor() is None


def test_floor_trim_needs_a_saved_gait(tmp_path):
    prof = tmp_path / "p.json"
    prof.write_text(json.dumps({"arm": {"current": None, "history": []}}))
    with pytest.raises(ValueError):
        A.set_floor_trim("arm", "tile", "fl=-0.1", path=str(prof))


def test_fall_recovery_is_off_for_the_arm_and_on_everywhere_else(monkeypatch):
    """User, 2026-10-25: the scripted self-right moves do not work with the claw payload; the serial link refuses them while the arm is fitted."""
    from pi_pipeline.link import opencat
    assert A.flag("fall_recovery", "arm") is False and A.flag("fall_recovery", "head") and A.flag("fall_recovery", "none")
    for att, refused in (("arm", True), ("head", False), ("none", False)):
        monkeypatch.setenv("G2_ATTACHMENT", att)
        for tok in opencat.RECOVERY_SKILLS:
            assert opencat.is_disabled(tok) is refused, (att, tok)
        assert not opencat.is_disabled("kbalance") and not opencat.is_disabled("kwkF")


def test_the_arm_stand_up_helpers_do_nothing_for_other_builds_and_the_plain_one_still_works(monkeypatch):
    """2026-10-25: the Pi never set the lift servo, so a walk from rest walked with the claw forward; a Pi-side lift ramp ended in a silent board. The arm build's stand-up ends on the
    firmware kbalance (which puts the lift at 0); the stock build and the head send nothing extra."""
    monkeypatch.setattr(__import__("pi_pipeline.gait.standup", fromlist=["x"]), "use_kskill", lambda p: False)       # this tests the older stand-up routine, which no longer runs on the arm (owner, 2026-11-08: the eased K stand-up is the only one)
    from pi_pipeline.gait import standup
    monkeypatch.delenv("G2_STAND_RAMP_S", raising=False)
    sent = []
    for att in ("none", "head"):
        monkeypatch.setenv("G2_ATTACHMENT", att)
        assert standup.rest_pose() == standup.REST_URDF_DEG and standup.balance_pose() == standup.BALANCE_URDF_DEG
        assert standup.stand_via_firmware(sent.append, lambda s: None, "d") is False and not sent
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    assert standup.rest_pose() == [64, -50, 64, -50, 74, -56, 74, -56] and standup.start_pose("kbalance") == standup.balance_pose()
    assert standup.stand_sequenced(sent.append, lambda s: None, "d") is False and not sent                            # the shipped arm profile stands up the plain way (2026-10-25 night, easing is off) ...
    assert standup.ramp_to_stand(sent.append, standup.move_cmd, [30, 30] * 4, lambda s: None, "d") is False            # no leg ramp (easing off) ...
    assert sent == ["kbalance"]                                                                                          # ... just the firmware's own stand-up
    sent.clear()
    assert standup.ramp_to_stand(sent.append, standup.move_cmd, [30, 30] * 4, lambda s: None, "kbalance") is False and not sent   # already standing: nothing


def test_the_arm_stands_up_rear_legs_first_with_the_front_following_soon_and_kbalance_before_the_end(monkeypatch, tmp_path):
    """2026-10-25: the firmware stand-up lifts all eight leg joints at once and G2 fell front right with the claw out ahead; the arm build raises the rear first and the front
    right behind it (no pause between), and the firmware kbalance (the lift servo's swing) goes out while the front legs finish."""
    monkeypatch.setattr(__import__("pi_pipeline.gait.standup", fromlist=["x"]), "use_kskill", lambda p: False)       # this tests the older stand-up routine, which no longer runs on the arm (owner, 2026-11-08: the eased K stand-up is the only one)
    from pi_pipeline.gait import standup
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    prof = A.load_profiles()
    prof["arm"]["poses"]["stand_via"] = "sequenced"                                                     # the shipped arm profile stands up with the plain firmware kbalance (2026-10-25 night); the sequence is still here
    path = str(tmp_path / "profiles.json")
    A.save_profiles(prof, path)
    monkeypatch.setattr(A, "PROFILES_PATH", path)
    sent = []
    assert standup.stand_sequenced(sent.append, lambda s: None, "d") is True
    assert "kbalance" not in sent and all(c.startswith("i1 ") for c in sent)                                               # the lift pair rides in every leg command; no firmware stand-up after it
    lifts = [int(c.split()[1]) for c in sent]
    assert lifts[0] == 60 and lifts[-1] == 0 and lifts == sorted(lifts, reverse=True)                                      # eased down from the rest angle to the walking angle
    legs = [standup.start_pose("i" + c[3:].split(" ", 1)[1]) for c in sent]
    rest, goal = standup.rest_pose(), standup.balance_pose()
    first_front = next(i for i, p in enumerate(legs) if p[:4] != rest[:4])
    first_rear = next(i for i, p in enumerate(legs) if p[4:] != rest[4:])
    assert first_rear < first_front and first_front <= int(standup.SEQ_FRONT_START_S * standup.STEPS_PER_S) + 2          # the rear moves first; the front starts about half a second in
    rear_half = next(i for i, p in enumerate(legs) if abs(p[5] - goal[5]) < abs(rest[5] - goal[5]) / 2)
    assert first_front <= rear_half + 2                                                                                  # the front starts by the time the rear is half way
    assert legs[-1] == goal                                                                                              # the legs end on the balance pose
    steps = [abs(a - b) for a, b in zip(lifts, lifts[1:])]
    assert max(steps) <= 4                                                                                               # the lift moves at most 4 deg a step (it was 6 over a shorter ramp: jerky)
    assert standup.stand_sequenced(sent.append, lambda s: None, "kbalance") is False                                     # only from rest
    sent.clear()
    for att in ("none", "head"):
        monkeypatch.setenv("G2_ATTACHMENT", att)
        assert standup.stand_sequenced(sent.append, lambda s: None, "d") is False and not sent


def test_with_fall_recovery_off_every_skill_and_every_connect_is_followed_by_gb(monkeypatch):
    """User, 2026-10-25: the firmware turns its gyro assist on with a skill (and on a restart), and with it on it keeps trying its own self-right after a fall, which shakes the Pi plug
    loose. The arm's link sends `gb` right after each skill and after connecting; the other attachments send nothing extra."""
    _arm_gyro_off(monkeypatch)
    from pi_pipeline.link.serial_link import SerialLink

    class FakeSerial:
        def __init__(self):
            self.out = []
            self.is_open = True
        def write(self, b):
            self.out.append(b.decode().strip())
        def flush(self):
            pass
        def reset_input_buffer(self):
            pass
        def close(self):
            pass
    for att, extra in (("arm", True), ("head", False), ("none", False)):
        monkeypatch.setenv("G2_ATTACHMENT", att)
        lk = SerialLink("/dev/null")
        lk._ser = FakeSerial()
        lk._ease_transition = lambda c: None
        lk.send("kbalance", read_reply=False, settle=0.0)
        lk.send("i8 30 9 30", read_reply=False, settle=0.0)
        lk._gyro_off_if_needed()
        assert lk._ser.out[0] == "kbalance" and ("gb" in lk._ser.out[1:2]) is extra, (att, lk._ser.out)
        assert "i8 30 9 30" in lk._ser.out


def test_a_stand_up_the_link_runs_itself_is_not_followed_by_the_firmware_stand_up(monkeypatch, tmp_path):
    """2026-10-25, hardware: G2 stood up, then again (the firmware plays kbalance from the rest posture it believes he is in) and the arm drew back: the kbalance that asked for the arm's own stand-up is not sent."""
    monkeypatch.setattr(__import__("pi_pipeline.gait.standup", fromlist=["x"]), "use_kskill", lambda p: False)       # this tests the older stand-up routine, which no longer runs on the arm (owner, 2026-11-08: the eased K stand-up is the only one)
    from pi_pipeline.link.serial_link import SerialLink

    class FakeSerial:
        def __init__(self):
            self.out = []
            self.is_open = True
        def write(self, b):
            self.out.append(b.decode().strip())
        def flush(self):
            pass
        def reset_input_buffer(self):
            pass
        def close(self):
            pass
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda s: None)
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    prof = A.load_profiles()
    prof["arm"]["poses"]["stand_via"] = "sequenced"                                                     # the sequence is still in the code; the shipped arm profile uses the plain stand-up
    path = str(tmp_path / "profiles_seq.json")
    A.save_profiles(prof, path)
    monkeypatch.setattr(A, "PROFILES_PATH", path)
    lk = SerialLink("/dev/null")
    lk._ser = FakeSerial()
    lk.last_motion_command = "d"
    lk.send("kbalance", read_reply=False, settle=0.0)
    assert "kbalance" not in lk._ser.out and any(c.startswith("i1 ") for c in lk._ser.out) and lk.last_motion_command == "kbalance"
    lk.send("kbalance", read_reply=False, settle=0.0)                      # standing now: a later kbalance goes through as a plain command
    assert lk._ser.out.count("kbalance") == 1


def test_a_gait_has_no_gb_next_to_it_but_a_posture_still_gets_one_after(monkeypatch):
    """2026-10-25, hardware: a `gb` right behind `kwkF` stopped the walk (0.2 in in 3 s, against about 20 in without it) and a `gb` right before it did the same in the chase (the distance to the ball never changed). The gyro
    is already off from the connect and the last posture; gaits get nothing; postures and tricks still get `gb` after."""
    _arm_gyro_off(monkeypatch)
    from pi_pipeline.link.serial_link import SerialLink

    class FakeSerial:
        def __init__(self):
            self.out = []
            self.is_open = True
        def write(self, b):
            self.out.append(b.decode().strip())
        def flush(self):
            pass
        def reset_input_buffer(self):
            pass
        def close(self):
            pass
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    for gait in ("kwkF", "kwkL", "kwkR", "kbkF"):
        lk = SerialLink("/dev/null")
        lk._ser = FakeSerial()
        lk._ease_transition = lambda c: None
        lk.send(gait, read_reply=False, settle=0.0)
        assert lk._ser.out == [gait], (gait, lk._ser.out)
    lk = SerialLink("/dev/null")
    lk._ser = FakeSerial()
    lk._ease_transition = lambda c: None
    lk.send("kbalance", read_reply=False, settle=0.0)
    assert lk._ser.out == ["kbalance", "gb"]


def test_blending_on_the_arm_uses_the_arm_firmwares_poses_and_first_frames(monkeypatch):
    """User, 2026-10-25: blending (pose to pose) is separate from easing and is back on for the arm; it blends into the ARM variant of a gait and the arm's shifted poses, not the stock tables."""
    from pi_pipeline.link import transitions as T
    monkeypatch.setenv("G2_ATTACHMENT", "none")
    stock_walk, stock_rest, stock_balance = T.target("kwkF"), T.pose_after(""), T.balance_pose()
    assert stock_rest == T.REST and stock_balance == T.BALANCE and stock_walk == T._resolve(T.table()["wkF"]["first"], None)      # the stock build is exactly as before (an F skill: the firmware picks a side at random, so the mean of the frame and its mirror)
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    rows = T.table()
    assert T.target("kwkF") == T._resolve(rows["wkArmF"]["first"], None)                                    # the walk the arm firmware really plays (not the stock wkF)
    assert T.target("kwkF") != T._resolve(rows["wkF"]["first"], None)
    assert T.target("kwkL") == [float(x) for x in rows["wkArmL"]["first"]]
    assert T.target("kwkR") == T.mirror([float(x) for x in rows["wkArmL"]["first"]])                         # R is the mirrored L
    assert T.target("kbkF") == T._resolve(rows["bkArmF"]["first"], None)
    assert T.pose_after("") == T.rest_pose() == [64.0, 64.0, 74.0, 74.0, -50.0, -50.0, -56.0, -56.0]       # the arm's rest, measured, in Petoi order
    assert T.balance_pose() == [15.0, 15.0, 20.0, 20.0, 56.0, 56.0, 50.0, 50.0]
    other = next(n for n, r in rows.items() if r["kind"] == "posture" and not n.endswith(("L", "R")) and n not in ("balance", "up", "rest") and "Arm" not in n and T.target("k" + n) is not None)
    stock = T._resolve(rows[other]["first"], None)
    shifted = T.target("k" + other)
    assert shifted == [stock[0] - 10, stock[1] - 10, stock[2], stock[3], stock[4] + 6, stock[5] + 6, stock[6], stock[7]]   # any other skill: the stock frame, front shoulders -10 and front knees +6
    assert T.target("kbalance") is None                                                                       # a stop stays a stop


def test_the_arms_walking_lift_is_off_until_set_and_sent_once_per_walk(monkeypatch, tmp_path):
    """User, 2026-11-01: the claw's carrying height while walking. Unset = nothing sent (the firmware's own, about 0-2); set = one `i1 N` after the stand-up."""
    from pi_pipeline.gait import standup
    prof = tmp_path / "profiles.json"
    prof.write_text(json.dumps({"arm": {"current": None, "history": [], "poses": {"stand_via": "kbalance", "arm_walk": 0}}, "head": {"current": None, "history": []}}))
    monkeypatch.setattr(A, "PROFILES_PATH", str(prof))
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    sent = []
    assert standup.walk_lift() is None and standup.apply_walk_lift(sent.append) is False and sent == []        # off by default
    A.set_walk_lift("arm", 12, path=str(prof))
    assert standup.walk_lift() == 12 and standup.apply_walk_lift(sent.append) is True and sent == ["i1 12"]
    A.set_walk_lift("arm", -5, path=str(prof))
    sent.clear()
    standup.apply_walk_lift(sent.append)
    assert sent == ["i1 -5"]
    with pytest.raises(ValueError):                                                                           # outside the saved range
        A.set_walk_lift("arm", 90, path=str(prof))
    with pytest.raises(ValueError):                                                                           # no poses (the head build): nothing to hold a lift in
        A.set_walk_lift("head", 10, path=str(prof))
    d = json.loads(prof.read_text())
    d["arm"]["poses"]["walk_lift_deg"] = 200                                                                  # a hand-edited value outside the range is ignored, not sent
    prof.write_text(json.dumps(d))
    sent.clear()
    assert standup.apply_walk_lift(sent.append) is False and sent == []
    A.set_walk_lift("arm", None, path=str(prof))
    assert "walk_lift_deg" not in json.loads(prof.read_text())["arm"]["poses"]
    monkeypatch.setenv("G2_ATTACHMENT", "none")
    assert standup.walk_lift() is None                                                                        # another build never sends it


def test_startup_asks_again_when_the_first_reply_is_a_leftover(monkeypatch):
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    monkeypatch.setattr(A, "BANNER_RETRY_GAP_S", 0.0)
    replies = iter(["X", "g", "Bittle X+Arm\nB10_260527"])

    class Arm:
        def send(self, cmd, **kw):
            return next(replies) if cmd == "?" else ""
    assert A.startup_check(Arm()) is True


def test_the_arm_runs_with_the_gyro_balance_on_when_asked_for_one_run(monkeypatch):
    """`G2_GYRO_BALANCE=1` (the A/B): `gB` goes out as `gB`, start-up sends no `gb`, and a skill is not followed by `gb`. Not the default: the board's own self-right flipped him with it on (2026-11-08)."""
    from pi_pipeline.link.serial_link import SerialLink
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    monkeypatch.setenv("G2_GYRO_BALANCE", "1")
    sent = []

    class Arm:
        def send(self, cmd, **kw):
            sent.append(cmd)
            return "Bittle X+Arm\nB10_260101" if cmd == "?" else ""
    assert A.startup_check(Arm()) is True
    assert "gb" not in sent

    class FakeSerial:
        def __init__(self):
            self.out = []
            self.is_open = True
        def write(self, b):
            self.out.append(b.decode().strip())
        def flush(self):
            pass
    lk = SerialLink("/dev/null")
    lk._ser = FakeSerial()
    monkeypatch.setattr(SerialLink, "is_connected", property(lambda self: True))
    lk.send("gB", read_reply=False, settle=0.0)
    lk._gyro_off_if_needed()
    assert lk._ser.out == ["gB"]


def test_an_env_switch_overrides_the_profile_flag_for_one_run(monkeypatch):
    """User, 2026-11-08: G2_GYRO_BALANCE=0 / 1 (any profile flag: G2_<KEY>) decides for a run, so the gyro balance can be A/B tested without editing the profile."""
    monkeypatch.delenv("G2_GYRO_BALANCE", raising=False)
    assert A.flag("gyro_balance", "arm") is False                      # the shipped arm profile
    monkeypatch.setenv("G2_GYRO_BALANCE", "1")
    assert A.flag("gyro_balance", "arm") is True and A.flag_safe("gyro_balance") in (True, False)
    monkeypatch.setenv("G2_GYRO_BALANCE", "0")
    assert A.flag("gyro_balance", "arm") is False
    assert A.flag("easing", "arm") is False                            # other flags untouched


def test_the_stand_up_ramp_runs_with_the_gyro_balance_off_and_turns_it_on_after(monkeypatch):
    """User, 2026-11-08: the arm runs with the gyro balance on; the firmware's balance loop fights an eased stand-up (2026-10-18), so the ramp is bracketed gb ... gB."""
    monkeypatch.setattr(__import__("pi_pipeline.gait.standup", fromlist=["x"]), "use_kskill", lambda p: False)       # this tests the older stand-up routine, which no longer runs on the arm (owner, 2026-11-08: the eased K stand-up is the only one)
    from pi_pipeline.gait import standup
    from pi_pipeline.link.serial_link import SerialLink
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    monkeypatch.setenv("G2_GYRO_BALANCE", "1")                          # on for this run (it is off by default)
    monkeypatch.setenv("G2_STAND_ATT_KSKILL", "0")                      # (the attention-pose stand-up is the board-played K skill by default since 2026-11-08: this tests the Pi-streamed one)
    out = []
    lk = SerialLink("/dev/null")
    lk._write_pose = out.append
    lk.last_motion_command = "kcalib"
    monkeypatch.setattr(standup, "stand_from_attention", lambda send, sleep, last: (send("i8 40"), True)[1])
    assert lk._stand_up() is not None
    assert out == ["gb", "i8 40", "gB"]
    out.clear()
    monkeypatch.setenv("G2_GYRO_BALANCE", "0")                          # gyro off (the default): nothing extra is sent
    lk.last_motion_command = "kcalib"
    assert lk._stand_up() is not None and out == ["i8 40"]


def test_the_voice_module_english_setting_is_not_sent_again_within_ten_minutes(monkeypatch, tmp_path):
    """2026-11-08: the service crash-looped 27 times in 20 minutes and sent XAc/XAa to the BiBoard on every restart."""
    import time as _t
    sent = []

    class Link:
        def send(self, cmd, **kw):
            sent.append(cmd)
            return ""
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    assert A.apply_voice_module_language(Link(), "arm") is True and sent == ["XAc", "XAa"]
    assert A.apply_voice_module_language(Link(), "arm") is False and sent == ["XAc", "XAa"]       # a moment later: skipped
    p = A._voice_module_stamp()
    open(p, "w").write(f"{_t.time() - A.VOICE_MODULE_MIN_GAP_S - 5:.0f}\n")                      # long ago: sent again
    assert A.apply_voice_module_language(Link(), "arm") is True and sent == ["XAc", "XAa", "XAc", "XAa"]


def test_gyro_gaits_switches_the_gyro_on_just_before_a_gait_and_never_around_postures(monkeypatch):
    """G2_GYRO_GAITS=1 (2026-11-08 experiment): `gB` goes out right before a scripted gait; postures and the stop are untouched (the board's own rc / up flipped him when the gyro was on in the attention pose)."""
    from pi_pipeline.link import serial_link
    from pi_pipeline.link.serial_link import SerialLink
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    monkeypatch.delenv("G2_GYRO_BALANCE", raising=False)
    monkeypatch.setattr(serial_link.time, "sleep", lambda s: None)
    monkeypatch.setattr(SerialLink, "is_connected", property(lambda self: True))

    class FakeSerial:
        def __init__(self):
            self.out = []
            self.is_open = True
        def write(self, b):
            self.out.append(b.decode().strip())
        def flush(self):
            pass

    def run(env):
        monkeypatch.setenv("G2_GYRO_GAITS", env)
        lk = SerialLink("/dev/null")
        lk._ser = FakeSerial()
        lk._ease_transition = lambda c: None
        for c in ("kwkR", "kbalance", "kcalib", "kwkF"):
            lk.send(c, read_reply=False, settle=0.0)
        return [x for x in lk._ser.out if x]
    off = run("0")
    assert "gB" not in off and off[0] == "kwkR"
    on = run("1")
    assert on[:2] == ["gB", "kwkR"]                                   # on, then the gait
    assert on.count("gB") == 2 and on[on.index("kwkF") - 1] == "gB"   # before each of the two gaits, nowhere else
    assert on[on.index("kbalance") - 1] == "kwkR" and "gB" not in on[on.index("kbalance"):on.index("kwkF") - 1]      # not before the stop or the attention pose


def test_the_arm_does_not_ask_the_firmware_at_start_but_still_turns_the_gyro_off(monkeypatch):
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    monkeypatch.delenv("G2_FIRMWARE_CHECK", raising=False)
    monkeypatch.delenv("G2_GYRO_BALANCE", raising=False)
    sent = []

    class Silent:                                  # a BiBoard that is off: it never answers
        def send(self, cmd, **kw):
            sent.append(cmd)
            return ""
    assert A.startup_check(Silent()) is True       # the stored attachment is trusted: no `?`, no wait, the skills stay
    assert "?" not in sent and sent[-1] == "gb"


def test_the_firmware_check_can_be_forced_on_for_one_run(monkeypatch):
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    monkeypatch.setenv("G2_FIRMWARE_CHECK", "1")
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    sent = []

    class Silent:
        def send(self, cmd, **kw):
            sent.append(cmd)
            return ""
    assert A.startup_check(Silent()) is False and "?" in sent
