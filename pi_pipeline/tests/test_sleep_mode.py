from pi_pipeline.behavior.sleep_mode import (
    SleepAction, SleepMode, SleepModeConfig, SleepState,
)


def _sm(**cfg):
    t = [0.0]
    s = SleepMode(SleepModeConfig(**cfg), clock=lambda: t[0])
    return s, t


def _run(s, t, secs, dt=1.0, **kw):
    out = (s.state, SleepAction.NONE)
    for _ in range(int(round(secs / dt))):
        t[0] += dt
        out = s.update(**kw)
    return out


def test_stays_awake_while_not_resting():
    s, t = _sm(sleep_after_resting_s=10.0)
    st, a = _run(s, t, 30.0, resting=False)
    assert st is SleepState.AWAKE and a is SleepAction.NONE


def test_falls_asleep_after_long_rest():
    s, t = _sm(sleep_after_resting_s=20.0, settle_timeout_s=2.0)
    st, a = _run(s, t, 18.0, resting=True)
    assert st is SleepState.AWAKE                       # not yet (~17s rested)
    t[0] += 5.0
    st, a = s.update(resting=True)                      # crosses the threshold
    assert st is SleepState.DOZING and a is SleepAction.ENTER_SLEEP
    s.settled()
    assert s.state is SleepState.ASLEEP


def test_doze_auto_advances_if_settled_never_called():
    s, t = _sm(sleep_after_resting_s=5.0, settle_timeout_s=3.0)
    _run(s, t, 6.0, resting=True)                       # -> DOZING
    assert s.state is SleepState.DOZING
    _run(s, t, 4.0, resting=True)                       # settle_timeout elapses
    assert s.state is SleepState.ASLEEP


def test_person_present_blocks_auto_sleep_but_not_the_command():
    s, t = _sm(sleep_after_resting_s=5.0, person_present_blocks=True)
    st, a = _run(s, t, 20.0, resting=True, person_present=True)
    assert st is SleepState.AWAKE
    assert "person present" in s.last_reason
    s.on_command_sleep()
    st, a = s.update(resting=True, person_present=True)
    assert st is SleepState.DOZING and a is SleepAction.ENTER_SLEEP


def test_imu_tap_wakes_it():
    s, t = _sm(sleep_after_resting_s=3.0, settle_timeout_s=1.0, min_sleep_s=5.0)
    _run(s, t, 4.0, resting=True)
    s.settled()
    assert s.state is SleepState.ASLEEP
    _run(s, t, 6.0, resting=True)                       # past min_sleep_s
    st, a = s.update(resting=True, imu_tap=True)
    assert st is SleepState.ROUSING and a is SleepAction.WAKE
    assert "imu tap" in s.last_reason


def test_min_sleep_s_suppresses_an_immediate_wake():
    s, t = _sm(sleep_after_resting_s=2.0, settle_timeout_s=1.0, min_sleep_s=10.0)
    _run(s, t, 3.0, resting=True)
    s.settled()
    st, a = _run(s, t, 3.0, resting=True, loud_sound=True)   # noisy, but < min_sleep_s
    assert st is SleepState.ASLEEP
    assert "min-sleep hold" in s.last_reason


def test_loud_sound_can_be_disabled_as_a_wake_trigger():
    s, t = _sm(sleep_after_resting_s=2.0, settle_timeout_s=1.0, min_sleep_s=1.0,
               loud_sound_wakes=False)
    _run(s, t, 3.0, resting=True)
    s.settled()
    st, _ = _run(s, t, 5.0, resting=True, loud_sound=True)
    assert st is SleepState.ASLEEP                      # ignored


def test_rouse_completes_on_wake_done_or_timeout():
    s, t = _sm(sleep_after_resting_s=1.0, settle_timeout_s=1.0, min_sleep_s=0.0,
               rouse_timeout_s=4.0)
    _run(s, t, 2.0, resting=True)
    s.settled()
    s.update(resting=True, wake_word=True)              # -> ROUSING
    assert s.state is SleepState.ROUSING
    s.wake_done()
    assert s.state is SleepState.AWAKE
    # and via timeout:
    s2, t2 = _sm(rouse_timeout_s=3.0)
    s2._state = SleepState.ROUSING
    s2._since = 0.0
    _run(s2, t2, 4.0, resting=True)
    assert s2.state is SleepState.AWAKE


def test_activity_rouses_from_asleep():
    s, t = _sm(sleep_after_resting_s=1.0, settle_timeout_s=1.0, min_sleep_s=0.0)
    _run(s, t, 2.0, resting=True)
    s.settled()
    s.on_activity()
    assert s.state is SleepState.ROUSING


def test_losing_resting_status_rouses():
    s, t = _sm(sleep_after_resting_s=1.0, settle_timeout_s=1.0)
    _run(s, t, 2.0, resting=True)
    s.settled()
    assert s.state is SleepState.ASLEEP
    st, a = s.update(resting=False)                     # IdlePosture got roused
    assert st is SleepState.ROUSING and a is SleepAction.WAKE


def test_reset():
    s, t = _sm(sleep_after_resting_s=1.0)
    _run(s, t, 3.0, resting=True)
    s.reset()
    assert s.state is SleepState.AWAKE
