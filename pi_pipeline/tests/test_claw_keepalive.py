"""The claw look re-sends the attention pose's leg angles while it holds, and skips throwaway pictures when it runs late."""
from pi_pipeline.behavior import claw_survey as C


class Link:
    def __init__(self, last="kcalib"):
        self.sent, self.last_motion_command, self.imu_print_on = [], last, True

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return ""


def _run(link, mp, snap=None):
    now = [0.0]
    mp.setattr(C.time, "monotonic", lambda: now[0])
    def sleep(s):
        now[0] += s
    return C.run_claw_look(link, snap, "look", sleep=sleep)


def test_leg_angles_are_resent_during_a_look_in_the_attention_pose(monkeypatch):
    link = Link()
    _run(link, monkeypatch)
    assert sum(1 for c in link.sent if c.count(" ") >= 15) >= 1                  # (the look no longer lowers the claw at the end: the rest pose does, so it is a few seconds shorter)


def test_nothing_is_resent_when_not_in_the_attention_pose(monkeypatch):
    link = Link(last="kbalance")
    _run(link, monkeypatch)
    assert not any(c.count(" ") >= 15 for c in link.sent)


def test_throwaway_pictures_are_skipped_when_late_but_the_counting_one_is_taken(monkeypatch):
    link, got = Link(), []
    now = [0.0]
    monkeypatch.setattr(C.time, "monotonic", lambda: now[0])
    def sleep(s):
        now[0] += s
    def snap(label):
        got.append(label)
        now[0] += 30.0                       # a camera that takes 30 s per picture
    C.run_claw_look(link, snap, "look", sleep=sleep)
    assert got[0] == "look_left" and got[-1] == "look" and "look_right" not in got


def test_a_missed_side_picture_skips_the_other_one(monkeypatch):
    link, got = Link(), []
    now = [0.0]
    monkeypatch.setattr(C.time, "monotonic", lambda: now[0])
    def snap(label):
        got.append(label)
        return None if label == "look_left" else "saved"
    C.run_claw_look(link, snap, "look", sleep=lambda s: now.__setitem__(0, now[0] + s), miss_skips=True)
    assert got == ["look_left", "look"]
