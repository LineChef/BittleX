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
