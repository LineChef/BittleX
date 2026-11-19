"""tools/g2_fall_report.py: the one-command fall printout and its rule-based class."""
import importlib.util
import os

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
_spec = importlib.util.spec_from_file_location("g2_fall_report_under_test", os.path.join(_TOOLS, "g2_fall_report.py"))
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


def fall(last="kwkF", roll=2.0, spread=1.0):
    rows = [[-6 + 0.5 * i, roll + (spread if i % 2 else 0.0), -3.0, 0, 0, 0, 0, 0, 0, 1] for i in range(11)]
    return {"when": "2026-11-18 09:41:10", "context": {"last_motion_command": last}, "summary": {"peak_tilt_deg": 80.0, "first_over_20_s": 0.3}, "commands": [{"t": "2026-11-18 09:41:08", "cmd": last}], "trace": rows}


def test_a_flipped_lie_down_near_the_fall_is_the_class():
    ld = [{"at": "2026-11-18 09:41:06", "why": "rest then stand", "before": [-20.0, 22.0], "after": {"1s": [0, 90], "3s": [0, 178]}, "peak_deg": 178.0, "flipped": True}]
    assert fr.classify(fall(), ld, [])[0] == "flipped in a lie-down"


def test_the_boards_own_move_beats_the_tilt_rules():
    assert fr.classify(fall(), [], ["BiBoard started a move the Pi did not send: 'balance'"])[0] == "board-initiated"


def test_a_steady_roll_before_the_trigger_is_rolled_before_the_move():
    assert fr.classify(fall(roll=21.0), [], [])[0] == "rolled before the move"


def test_a_lie_down_command_is_a_transition_and_a_clean_tilt_is_mid_move():
    assert fr.classify(fall(last="krest"), [], [])[0] == "transition"
    assert fr.classify(fall(last="kwkL"), [], [])[0] == "mid-move with a clean tilt before"
    assert fr.classify(None, [], [])[0] == "unknown"


def test_the_report_lists_lie_downs_sags_and_the_class():
    ld = [{"at": "2026-11-18 09:41:06", "why": "rest then stand", "before": [0.0, 10.0], "after": {"1s": [0, 12], "3s": [0, 8]}, "peak_deg": 12.0, "flipped": False, "pack_v": 7.9}]
    sg = [{"at": "2026-11-18 09:40:30", "pitch": -20.0, "roll": 3.0, "since_stand_s": 40, "last_move": "kvtR", "pack_live_v": 7.8}]
    text = "\n".join(fr.report(fall(), ld, sg, []))
    assert "lie-down 09:41:06" in text and "sag 09:40:30" in text and "pack 7.8" in text and "class:" in text and "fall-analysis" in text


def test_events_near_the_fall_are_picked_by_time():
    rows = [{"at": "2026-11-18 09:30:00"}, {"at": "2026-11-18 09:40:00"}, {"at": "2026-11-18 09:41:00"}, {"at": "2026-11-18 09:50:00"}]
    t = fr._when("2026-11-18 09:41:10")
    assert [r["at"][11:16] for r in fr.near(rows, t, 120.0)] == ["09:40", "09:41"]
    assert fr.parse_lines('{"a": 1}\nnot json\n[1]') == [{"a": 1}]
