"""The shared link's lock wrapper (link/locked.py) passes through what a goal inside the voice service needs from the real link."""
import pytest

from pi_pipeline.link.locked import LockedLink


class Real:
    def __init__(self):
        self.played = []

    def _quiet_active(self):
        return False

    def _end_quiet(self, flush=True):
        self.ended = flush

    def play_data_skill(self, message):
        self.played.append(message)

    def send(self, command, **kw):
        return "ok"


def test_the_data_skill_and_the_quiet_state_reach_the_real_link():
    real = Real()
    link = LockedLink(real)
    assert link._quiet_active() is False                                      # the pick-up waits on it (behavior/catapult.py)
    link._end_quiet()
    assert real.ended is True
    link.play_data_skill(b"abc")
    assert real.played == [b"abc"]
    assert link.send("x") == "ok"


def test_a_name_the_real_link_does_not_have_is_still_an_attribute_error():
    link = LockedLink(Real())
    with pytest.raises(AttributeError):
        link.no_such_thing
    with pytest.raises(AttributeError):
        link.__deepcopy_x__
