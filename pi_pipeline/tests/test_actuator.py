from pi_pipeline.voice.actuator import MockActuator, SerialActuator, make_actuator


class FakeLink:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, cmd, read_reply=True):
        self.sent.append(cmd)
        return ""

    def close(self):
        self.closed = True


def test_shared_link_is_not_closed_by_the_actuator():
    lk = FakeLink()
    act = SerialActuator("ignored", 0, link=lk)
    act.perform("sit")
    act.close()
    assert lk.sent and not lk.closed   # the link's lifecycle belongs to whoever built it


def test_make_actuator_serial_passes_the_shared_link_through():
    lk = FakeLink()
    act = make_actuator("serial", port="ignored", baud=0, link=lk)
    assert isinstance(act, SerialActuator)
    act.perform("wave")
    assert lk.sent == ["khi"]


def test_make_actuator_mock_ignores_link():
    act = make_actuator("mock", port="ignored", baud=0, link=FakeLink())
    assert isinstance(act, MockActuator)


def test_gait_cap_stops_a_looping_gait():
    import time
    lk = FakeLink()
    act = SerialActuator("ignored", 0, link=lk, max_continuous_s=0.05)
    act.perform("walk_forward")
    time.sleep(0.2)
    assert lk.sent == ["kwkF", "d"]      # the cap fired the stop command


def test_gait_cap_ignores_one_shot_skills_and_cancels_on_stop():
    import time
    lk = FakeLink()
    act = SerialActuator("ignored", 0, link=lk, max_continuous_s=0.05)
    act.perform("sit")                    # not a looping gait: no timer
    act.perform("walk_forward")
    act.stop()                            # explicit stop cancels the pending cap
    time.sleep(0.2)
    assert lk.sent == ["ksit", "kwkF", "d"]


def test_gait_cap_off_by_default():
    import time
    lk = FakeLink()
    act = SerialActuator("ignored", 0, link=lk)
    act.perform("walk_forward")
    time.sleep(0.1)
    assert lk.sent == ["kwkF"]


def test_gait_cap_follows_the_env_setting_when_not_passed(monkeypatch):
    import dataclasses

    import pi_pipeline.config as cfg
    lk = FakeLink()
    monkeypatch.setattr(cfg, "settings", dataclasses.replace(cfg.settings, max_gait_s=7.0))
    assert make_actuator("serial", port="x", baud=0, link=lk)._max_continuous_s == 7.0
    assert make_actuator("serial", port="x", baud=0, link=lk, max_continuous_s=2.0)._max_continuous_s == 2.0
    assert make_actuator("serial", port="x", baud=0, link=lk, max_continuous_s=0.0)._max_continuous_s == 0.0


def test_requested_seconds_stop_a_looping_gait_after_that_long():
    import time
    lk = FakeLink()
    act = SerialActuator("ignored", 0, link=lk)            # no standing cap
    act.perform("walk_forward", seconds=0.05)
    time.sleep(0.2)
    assert lk.sent == ["kwkF", "d"]


def test_standing_cap_is_a_ceiling_over_a_longer_request():
    import time
    lk = FakeLink()
    act = SerialActuator("ignored", 0, link=lk, max_continuous_s=0.05)
    act.perform("walk_forward", seconds=30)                # asks for much longer than the cap
    time.sleep(0.2)
    assert lk.sent == ["kwkF", "d"]


def test_seconds_ignored_for_one_shot_skills_and_bad_values():
    import time
    lk = FakeLink()
    act = SerialActuator("ignored", 0, link=lk)
    act.perform("sit", seconds=0.05)                       # not a looping gait
    act.perform("walk_forward", seconds="soon")            # not a number
    act.perform("walk_forward", seconds=-3)                # not positive
    time.sleep(0.15)
    assert lk.sent == ["ksit", "kwkF", "kwkF"]             # no stop was scheduled


def test_clamp_seconds():
    from pi_pipeline.voice import skills
    assert skills.clamp_seconds(8) == 8.0
    assert skills.clamp_seconds(500) == skills.MAX_GAIT_SECONDS
    assert skills.clamp_seconds(None) is None
    assert skills.clamp_seconds(0) is None
    assert skills.clamp_seconds(float("nan")) is None
