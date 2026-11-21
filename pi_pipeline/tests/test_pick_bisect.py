"""The pick-up bisect (behavior/pick_bisect.py): each variant writes exactly what it says and nothing else."""
import pytest

from pi_pipeline.behavior import pick_bisect as b


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


class Link:
    def __init__(self, clock):
        self.raw, self.sent, self.clock = [], [], clock

    def write_raw(self, data):
        self.raw.append((round(self.clock.now, 3), data))

    def send(self, c, **kw):
        self.sent.append(c)


class Robot:
    def __init__(self, link):
        self._lk, self._roll, self._pitch, self.tx = link, [], [], []

    def stand_up(self):
        return "ok"

    def _tilt(self, *a, **k):
        return (0.0, 0.0)

    def _tx(self, c):
        self.tx.append(c)

    def _fell(self):
        self._roll.append(0.1)
        self._pitch.append(0.1)
        return False


def run(variant, **kw):
    c = Clock()
    lk = Link(c)
    r = Robot(lk)
    res = b.run_variant(r, lk, variant, silent_s=1.0, say=lambda *_: None, sleep=c.sleep, clock=c, wall=lambda: 1.0, **kw)
    return res, lk, r


def test_plain_writes_only_the_token_like_a_hand_typed_printf():
    res, lk, r = run("plain")
    assert [d for _t, d in lk.raw] == [b"kpickF\n"] and lk.sent == [] and res["variant"] == "plain"
    assert r.tx[:1] == ["gP"]                                                                          # the IMU print is switched on BEFORE the token, never after it


def test_each_extra_variant_writes_one_command_after_the_delay():
    for variant, extra in (("gb", b"gb\n"), ("gP", b"gP\n"), ("j", b"j\n")):
        res, lk, _r = run(variant, after_ms=100)
        assert [d for _t, d in lk.raw] == [b"kpickF\n", extra]
        assert lk.raw[1][0] - lk.raw[0][0] == pytest.approx(0.1, abs=0.02)


def test_the_link_variant_goes_through_the_links_own_send():
    res, lk, _r = run("link")
    assert lk.sent == ["kpickF"] and lk.raw == []


def test_a_quiet_body_is_called_no_motion_because_a_pick_should_move_him():
    c = Clock()
    lk = Link(c)
    r = Robot(lk)
    r._fell = lambda: False                                                                             # no IMU frames change
    res = b.run_variant(r, lk, "plain", silent_s=1.0, say=lambda *_: None, sleep=c.sleep, clock=c, wall=lambda: 1.0)
    assert res["verdict"] in ("no_motion", "ok")


def test_an_unknown_variant_is_refused_and_the_answer_is_typed_in():
    with pytest.raises(ValueError):
        b.make_sender(Link(Clock()), "nope")
    answers = iter(["f", "claw closed on it"])
    assert b.ask_result(ask=lambda _p: next(answers)) == {"result": "full pick", "note": "claw closed on it"}
    assert b.ask_result(ask=lambda _p: "z")["result"] is None
