import types

import pytest

from pi_pipeline.features import DEFAULT_PROFILE, PROFILES, Features


def _f(spec):
    return Features.from_spec(spec)


def _resolved(spec):
    return _f(spec).resolve()[0]


def test_default_is_everything_on():
    f = _f("")
    assert f.gait == "policy" and f.power_profile == "headless"
    assert f.memory and f.claude and f.explore and f.vision_perception
    assert not f.estop


def test_profiles_are_cumulative():
    p0, p2, p5, p9 = (PROFILES["p0-link"], PROFILES["p2-gait"],
                      PROFILES["p5-voice"], PROFILES["p9-full"])
    assert p0["link"] and not p0["imu"] and p0["gait"] == "off"
    assert p2["gait"] == "scripted" and p2["thermal_guard"] and not p2["vision_safety"]
    assert p5["stt"] and p5["claude"] and not p5["wake_word"]
    assert p9["gait"] == "policy" and p9["memory"] and p9["explore"]


def test_profile_token_and_short_alias():
    assert _f("profile:p2-gait").gait == "scripted"
    assert _f("profile:p2").gait == "scripted"          # short alias
    assert _f("profile:p5-voice").mic and not _f("profile:p5-voice").wake_word


def test_unknown_profile_falls_back_to_default(caplog):
    f = _f("profile:nope")
    assert f.gait == PROFILES[DEFAULT_PROFILE]["gait"]


def test_plus_minus_overrides():
    f = _f("profile:p2-gait, +vision_safety, -thermal_guard")
    assert f.vision_safety and not f.thermal_guard
    assert _f("-explore").explore is False


def test_mode_field_tokens():
    assert _f("gait:scripted").gait == "scripted"
    assert _f("fall_detect:alert").fall_detect == "alert"
    assert _f("power_profile:interactive").power_profile == "interactive"
    # bad value ignored, keeps default
    assert _f("gait:sprint").gait == "policy"


def test_unknown_tokens_are_skipped():
    f = _f("+nonsense, wat:huh, -memory")
    assert f.memory is False           # the valid one still applied


def test_resolve_estop_holds_actuation():
    f = _resolved("+estop")
    assert f.gait == "off" and not f.explore and not f.idle_rest and not f.avoidance_act
    assert f.fall_detect in ("alert", "off")


def test_resolve_gait_off_disables_dependents():
    f = _resolved("gait:off")
    assert not f.explore and not f.idle_rest and not f.avoidance_act and not f.thermal_guard


def test_resolve_no_mic_disables_stt_and_wake():
    f = _resolved("profile:p6-wake, -mic")
    assert not f.stt and not f.wake_word


def test_resolve_no_vision_safety_disables_avoidance_and_explore():
    f = _resolved("profile:p9-full, -vision_safety")
    assert not f.avoidance_act and not f.explore


def test_resolve_no_link_cascades():
    f = _resolved("-link")
    assert f.gait == "off" and f.fall_detect == "off"
    assert not f.explore and not f.thermal_guard


def test_resolve_no_imu_drops_policy():
    f = _resolved("-imu")
    assert f.gait in ("scripted", "off") and f.fall_detect == "off"


def test_resolve_returns_notes():
    _, notes = _f("+estop").resolve()
    assert notes and any("estop" in n for n in notes)


def test_from_settings():
    s = types.SimpleNamespace(features_spec="profile:p0-link")
    assert Features.from_settings(s).gait == "off"


def test_describe_smoke():
    text = _f("").describe()
    assert "gait:policy" in text and "+memory" in text and "power_profile:headless" in text


def test_enabled_helper():
    f = _f("profile:p2-gait")
    assert f.enabled("thermal_guard") and not f.enabled("memory")
    assert f.enabled("gait")            # "scripted" is not "off"
    assert not _f("gait:off").enabled("gait")
