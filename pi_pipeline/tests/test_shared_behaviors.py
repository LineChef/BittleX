"""One behavior in every mode (owner, 2026-11-10): the shared helpers the chase, the exploration, the goals and the scripts all use."""
import io
import math

from pi_pipeline.behavior import ball_chase as bc


class _Link:
    """A link that answers `j` with the joint angles it is told to report, and records what was sent."""
    def __init__(self, reads):
        self.sent, self._reads, self._other = [], list(reads), []

    def send(self, c, **kw):
        self.sent.append(c)
        if c == "j" and self._reads:
            j = self._reads.pop(0)
            self._other.append(",".join(str(x) for x in j) if j else "")

    def poll_imu(self):
        return []

    def pop_other(self):
        out, self._other = self._other, []
        return out


def test_the_claw_is_asked_for_the_centre_again_until_the_board_reads_it_centred():
    off = [30, 40] + [0] * 14
    ok = [0, 0] + [0] * 14
    lk = _Link([off, ok])
    assert bc.ensure_claw_centered(lk, sleep=lambda s: None) is True
    assert lk.sent.count("i0 0 1 0") == 2                       # the first read was off: asked again
    lk2 = _Link([off, off, off])
    assert bc.ensure_claw_centered(lk2, sleep=lambda s: None, tries=3) is False and lk2.sent.count("i0 0 1 0") == 3


def test_the_claw_path_is_one_eased_stepping_for_every_move():
    pts = list(bc.claw_path((0, 0), (30, 40)))
    assert pts[-1] == (30, 40) and all(0 <= p <= 30 and 0 <= q <= 40 for p, q in pts)
    assert pts == sorted(pts)                                   # eased, never going backwards


def test_the_wall_stuck_rule_is_shared_by_the_chase_and_the_exploration_driver():
    st = {}
    for _ in range(2):
        bc.wall_stuck_count(8.0, st)
    assert st["stuck"] == 2 and bc.wall_stuck_count(20.0, st) == 0
    from pi_pipeline.behavior.driver import BehaviorDriver
    d = BehaviorDriver.__new__(BehaviorDriver)

    class W:
        def __init__(self, t, nearest):
            self.t, self.nearest_in = t, nearest
    assert [d._wall_unbelieved(W(t, 8.0)) for t in (1, 2, 3)] == [False, False, True]      # the third look in a row at the closest row is not believed
    assert d._wall_unbelieved(W(3, 8.0)) is True                                              # the same look is not counted twice
    assert d._wall_unbelieved(W(4, 30.0)) is False                                            # any other reading believes again


def test_a_rest_is_confirmed_with_the_boards_pose_read():
    from pi_pipeline.gait import standup
    rest = [0] * 16
    for k in range(8):
        from pi_pipeline.link import kskill
        rest[kskill.URDF_TO_SERVO[k]] = standup.rest_pose()[k]
    lk = _Link([rest])
    assert bc.ensure_rest(lk, sleep=lambda s: None) is True
    assert lk.sent.count("krest") == 1 and lk.sent[-1] == "d"
    lk2 = _Link([[10] * 16, [10] * 16, [10] * 16])
    assert bc.ensure_rest(lk2, sleep=lambda s: None, tries=3) is False and lk2.sent.count("krest") == 3 and lk2.sent[-1] == "d"
    lk3 = _Link([])                                             # a link that cannot be read: the one rest command, then `d`
    assert bc.ensure_rest(lk3, sleep=lambda s: None) is False and lk3.sent.count("krest") == 1


def test_a_picture_rolled_from_level_is_a_sag_hint():
    from PIL import Image, ImageDraw
    from pi_pipeline.vision import picture_tilt as pt

    def jpeg(ang):
        im = Image.new("L", (240, 240), 200)
        d = ImageDraw.Draw(im)
        c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        for off in (-60, 0, 60):
            d.line([(120 - 200 * c + off * s, 120 - 200 * s - off * c), (120 + 200 * c + off * s, 120 + 200 * s - off * c)], fill=40, width=5)
        for off in (-50, 30):
            d.line([(120 + 200 * s + off * c, 120 - 200 * c + off * s), (120 - 200 * s + off * c, 120 + 200 * c + off * s)], fill=40, width=5)
        b = io.BytesIO()
        im.save(b, "JPEG")
        return b.getvalue()
    level, rolled = pt.estimate(jpeg(0)), pt.estimate(jpeg(20))
    assert abs(level[0]) < 3 and not pt.flagged(level)
    assert 16 <= rolled[0] <= 24 and pt.flagged(rolled)
    assert pt.estimate(None) is None and pt.estimate(b"not a jpeg") is None
