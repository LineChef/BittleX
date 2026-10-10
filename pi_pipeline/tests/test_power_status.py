"""'What is your power level': percent for the pack and an estimate for the Pi, and the sleep summary from the power log."""
import types

from pi_pipeline.power.battery import pack_percent
from pi_pipeline.power.power_log import sleep_stats
from pi_pipeline.power.status import battery_report, pack_phrase, pi_phrase
from pi_pipeline.voice.commands import asks_battery, match_local_command


def test_pack_voltage_becomes_percent_matching_the_alarm_levels():
    assert pack_percent(8.4) == 100 and pack_percent(7.54) == 30 and pack_percent(7.46) == 20 and pack_percent(6.0) == 0
    assert 77 <= pack_percent(8.0) <= 79 and pack_percent(9.0) == 100


class Tracker:
    def __init__(self, full=11800.0, elapsed=5900.0, state="since_boot"):
        self._full, self._elapsed, self._state = full, elapsed, state

    def battery_state(self): return self._state, self._elapsed
    def mean_runtime_s(self, sources=None): return self._full
    def armed_elapsed_s(self, from_boot=False): return self._elapsed


def test_the_spoken_report_gives_percent_never_volts_and_says_when_it_cannot_read_or_is_told_he_is_plugged_in():
    assert pack_phrase(7.7) == "My battery is at about 55 percent."
    assert pack_phrase(None) == "I can't read my battery while I'm walking."
    r = battery_report(7.7, Tracker())
    assert "55 percent" in r and "The Pi has about 50 percent left, roughly 1 hours 38 minutes." in r and "V" not in r.replace("Pi", "")
    assert "plugged in" in battery_report(7.7, Tracker(state="paused"))
    assert pi_phrase(types.SimpleNamespace(battery_state=lambda: ("since_boot", 0), mean_runtime_s=lambda sources=None: None, armed_elapsed_s=lambda from_boot=False: 10.0)) is None


def test_the_battery_phrases_are_matched_as_a_local_command_and_other_commands_are_not_stolen():
    for t in ("what is your power level", "How much battery do you have left?", "gee two how much battery do you have", "what's your battery level"):
        assert asks_battery(t) and match_local_command(t) == "battery_query", t
    assert match_local_command("what floor are you on") == "floor_query" and match_local_command("walk forward") == "walk" and not asks_battery("you're unplugged")


def test_sleep_stats_count_sleeps_their_length_and_what_woke_him():
    rows = [{"boot": "b1", "t": 0.0, "event": "start"}, {"boot": "b1", "t": 300.0, "event": "sleep"}, {"boot": "b1", "t": 480.0, "event": "wake", "why": "wake word"},
            {"boot": "b1", "t": 900.0, "event": "sleep"}, {"boot": "b1", "t": 1000.0, "event": "alive"}]            # the second sleep is still going when the log ends
    s = sleep_stats(rows)
    assert s["boots"] == 1 and s["sleeps"] == 2 and s["sleep_s"] == [180.0, 100.0] and s["longest_s"] == 180.0 and s["wake_reasons"] == {"wake word": 1}
    assert abs(s["asleep_share"] - 0.28) < 0.001


def test_the_voice_loop_battery_handler_imports_the_report_function():
    """`pi_pipeline.power.status` is also a function exported by the package, so `from ..power import status` gave the function (crashed the loop on 2026-10-10)."""
    import inspect
    from pi_pipeline.voice import loop
    src = inspect.getsource(loop)
    assert "from ..power.status import battery_report" in src and "from ..power import status" not in src
