import re

from pi_pipeline.link import imu_print, kskill


class FakeLink:
    def __init__(self, on):
        self.sent, self.imu_print_on = [], on
        self._rows = ["0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15"]

    def send(self, c, **kw):
        self.sent.append(c)
        if c in ("gP", "gp"):
            self.imu_print_on = c == "gP"
        return ""

    def poll_imu(self):
        return []

    def pop_other(self):
        rows, self._rows = self._rows, ["10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25"] if self.sent.count("j") else self._rows
        return rows if self.sent.count("j") else []


def test_a_pause_puts_the_print_back_only_if_it_was_on():
    on, off = FakeLink(True), FakeLink(False)
    with imu_print.paused(on):
        assert on.sent == ["gp"] and not on.imu_print_on
    assert on.sent == ["gp", "gP"] and on.imu_print_on
    with imu_print.paused(off):
        pass
    assert off.sent == ["gp"] and not off.imu_print_on


def test_the_pose_read_leaves_the_print_on_when_it_was_on():
    lk = FakeLink(True)
    got = kskill.read_joints(lk, timeout_s=0.3, sleep=lambda s: None, clock=iter([0.0, 0.1, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8]).__next__)
    assert lk.sent[0] == "gp" and "j" in lk.sent and lk.sent[-1] == "gP" and lk.imu_print_on
    assert got is None or len(got) == 16
    assert not re.search(r"gp$", "".join(lk.sent[-1:]))


def test_the_claw_look_leaves_the_print_as_it_found_it(monkeypatch):
    from pi_pipeline.behavior import claw_survey
    import pi_pipeline.behavior.ball_chase as bc
    monkeypatch.setattr(claw_survey, "_smooth", lambda *a, **k: None)
    monkeypatch.setattr(bc, "ensure_claw_centered", lambda *a, **k: None)
    for was_on in (True, False):
        lk = FakeLink(was_on)
        claw_survey.run_claw_look(lk, None, "look_centre", sleep=lambda s: None)
        assert lk.imu_print_on is was_on, was_on
