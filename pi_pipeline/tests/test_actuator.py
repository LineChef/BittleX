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
