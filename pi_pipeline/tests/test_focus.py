"""The focus lock (pi_pipeline/focus.py): while held, G2's own initiative (the explore ask, the sleep descent, the idle layer) stands aside; commands, stop and the guards never do."""
import json
import os
import re

import pytest

from pi_pipeline import focus
from pi_pipeline.behavior.driver import BehaviorDriver, DriverInputs


@pytest.fixture(autouse=True)
def _lockfile(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_FOCUS_FILE", str(tmp_path / "focus.json"))
    focus._last_logged.clear()


def test_a_hold_lasts_until_it_expires_and_a_second_holder_keeps_it_held():
    focus.hold("goal:ball_punt", "goal session", 60, now=1000.0)
    assert focus.held(now=1030.0) and not focus.held(now=1061.0)
    focus.hold("manual", "by hand", 600, now=1000.0)
    focus.hold("goal:ball_punt", "goal session", 60, now=1000.0)
    assert set(focus.holders(now=1100.0)) == {"manual"}                                # the run's hold ran out, the person's did not
    focus.release("manual")
    assert not focus.held(now=1100.0)


def test_a_crashed_holder_frees_the_lock_by_itself():
    focus.hold("goal:x", "", focus.DEFAULT_TTL_S, now=0.0)                             # never refreshed again
    assert focus.held(now=focus.DEFAULT_TTL_S - 1) and not focus.held(now=focus.DEFAULT_TTL_S + 1)


def test_allow_says_no_while_held_counts_what_was_held_back_and_logs_once_a_minute(caplog):
    assert focus.allow("explore_ask", now=10.0) is True
    focus.hold("manual", "testing", 600, now=10.0)
    with caplog.at_level("INFO", logger="g2.focus"):
        assert focus.allow("explore_ask", now=11.0) is False
        assert focus.allow("explore_ask", now=12.0) is False
        assert focus.allow("sleep", now=12.0) is False
    assert sum("autonomy held back (explore_ask)" in r.message for r in caplog.records) == 1
    st = focus.status(now=13.0)
    assert st["held"] and st["held_back"] == {"explore_ask": 2, "sleep": 1}
    focus.release("manual")
    focus.hold("manual", "again", 600, now=20.0)
    assert focus.status(now=21.0)["held_back"] == {}                                    # a fresh hold starts a fresh count


def test_holding_context_holds_for_the_block_and_always_releases(monkeypatch):
    with pytest.raises(RuntimeError):
        with focus.holding("goal:x", "goal session", refresh_s=0.01):
            assert focus.held()
            raise RuntimeError("the session crashed")
    assert not focus.held()


def test_the_manual_command_is_capped_and_off_releases_only_the_manual_hold(capsys):
    assert focus.main(["on", "9999", "hardware", "session"]) == 0
    left = focus.status()["holders"]["manual"]["seconds_left"]
    assert focus.MANUAL_MAX_MIN * 60 - 5 <= left <= focus.MANUAL_MAX_MIN * 60
    focus.hold("goal:x", "goal session", 60)
    assert focus.main(["off"]) == 0 and set(focus.holders()) == {"goal:x"}
    assert "still held by goal:x" in capsys.readouterr().out
    assert focus.main(["on", "abc"]) == 2


class _Clock:
    t = 0.0

    def __call__(self):
        return self.t


def _driver():
    c = _Clock()
    return BehaviorDriver(clock=c), c


def test_a_held_lock_keeps_the_idle_layer_from_settling_him():
    (held, hc), (free, fc) = _driver(), _driver()
    for t in range(0, 600, 5):                                                         # a long quiet: the free driver sits and rests, the held one stays as he is
        hc.t = fc.t = float(t)
        held.tick(DriverInputs(focus_held=True))
        free.tick(DriverInputs())
    assert held.idle.posture.value == "active" and free.idle.posture.value != "active"
    assert held._last_reason == "idle: held by the focus lock"


def test_a_held_lock_does_not_stop_the_stop_command_or_a_spoken_roam():
    d, c = _driver()
    c.t = 1.0
    assert d.tick(DriverInputs(focus_held=True, told_stop=True)) is not None           # commands are still processed
    d, c = _driver()
    for t in (1.0, 2.0, 3.0):
        c.t = t
        d.tick(DriverInputs(focus_held=True, arm_explore=(t == 2.0)))                  # a roam the person asked for is not held back by the lock
    assert d._last_reason.startswith("explore")


def test_every_autonomous_entry_in_the_voice_service_asks_the_lock():
    """Parity: the explore ask and the sleep descent of the service go through focus.allow (one function), and the runtime feeds the driver from focus.held."""
    root = os.path.join(os.path.dirname(__file__), "..")
    voice = open(os.path.join(root, "voice", "__main__.py")).read()
    assert 'focus.allow("explore_ask")' in voice and '_focus.allow("sleep")' in voice
    assert "focus_held=_focus.held()" in open(os.path.join(root, "behavior", "runtime.py")).read()
    assert "focus.holding(" in open(os.path.join(root, "goals", "runner.py")).read()
    assert "focus.holding(" in open(os.path.join(root, "explore_session.py")).read()


def test_the_state_file_is_plain_json_a_person_can_read():
    focus.hold("manual", "x", 60, now=5.0)
    d = json.load(open(os.environ["G2_FOCUS_FILE"]))
    assert re.fullmatch(r"manual", next(iter(d["holders"])))
