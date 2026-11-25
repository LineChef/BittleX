"""tools/g2_goal_run_report.py and tools/g2_finder_regress.py: the pure parts (the Pi and the picture folders are not needed)."""
import importlib.util
import sys
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_t", TOOLS / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS.parent))
    spec.loader.exec_module(m)
    return m


ROWS = [
    {"kind": "session_start", "time": "2026-11-25 10:00:00", "session": "a", "goal": "basket"},
    {"kind": "attempt", "session": "a", "goal": "basket", "number": 1, "ended": "made", "outcome": {"code": "made", "score": 1.0}, "seconds": 80.0, "settings": {"standoff_in": 16.0}},
    {"kind": "session_end", "time": "2026-11-25 10:02:00", "session": "a", "goal": "basket", "why": "made"},
    {"kind": "session_start", "time": "2026-11-25 10:10:00", "session": "b", "goal": "ball_punt"},
    {"kind": "session_end", "time": "2026-11-25 10:12:00", "session": "b", "goal": "ball_punt", "why": "max_attempts"},
    {"kind": "session_start", "time": "2026-11-25 10:20:00", "session": "c", "goal": "basket"},
]


def test_the_newest_finished_sessions_of_a_goal_are_picked_out_of_the_journal():
    rr = load("g2_goal_run_report")
    got = rr.sessions(ROWS, last=2)
    assert [s["session"] for s in got] == ["a", "b"]                                                  # c has not ended
    assert [s["session"] for s in rr.sessions(ROWS, "basket", 1)] == ["a"] and rr.sessions(ROWS, "basket")[0]["why"] == "made" and len(rr.sessions(ROWS, "basket")[0]["attempts"]) == 1
    assert rr.parse_rows('{"kind": "x"}\nnot json\n{"kind": "y"}\n') == [{"kind": "x"}, {"kind": "y"}]


def test_the_journal_lines_that_matter_are_kept_and_the_repeated_arcs_collapse():
    rr = load("g2_goal_run_report")
    text = "\n".join([
        "Nov 25 10:30:04 g2pi python[8]: 10:30:04 g2.goal attempt 1: pick up and throw",
        "Nov 25 10:30:05 g2pi python[8]: 10:30:05 g2.vision unrelated line",
        "Nov 25 10:34:30 g2pi python[8]: 10:34:30 g2.goal circle: circling: wide arc round the tub (arc 45.0, 0 degrees round)",
        "Nov 25 10:34:39 g2pi python[8]: 10:34:39 g2.goal circle: circling: wide arc round the tub (arc 45.0, 45 degrees round)",
        "Nov 25 10:34:48 g2pi python[8]: 10:34:48 g2.goal circle: circling: wide arc round the tub (arc 45.0, 90 degrees round)",
        "Nov 25 10:35:28 g2pi python[8]: 10:35:28 g2.snapshot camera: no answer after 2.5 s: asking again",
        "Nov 25 10:50:55 g2pi python[8]:   G2: I fell down. I have stopped.",
    ])
    ev = rr.journal_events(text, "2026-11-25")
    assert [t for t, _x in ev][:2] == [10 * 3600 + 30 * 60 + 4, 10 * 3600 + 34 * 60 + 30] and not any("unrelated" in x for _t, x in ev)
    col = rr.collapse(ev)
    arcs = [c for c in col if "wide arc" in c[1]]
    assert len(arcs) == 1 and arcs[0][2] == 3 and rr.fmt(arcs[0][3]) == "10:34:48"                   # three arcs, one line, and when the last one ran
    assert any("I fell down" in x for _t, x in ev) and any("asking again" in x for _t, x in ev)
    assert rr.gaps([0, 5, 30, 33, 50], 12) == [(5, 30, 25), (33, 50, 17)] and rr.gaps([0, 5], 12) == []


def test_the_picture_log_lines_show_the_readings_and_the_blob_check_finds_a_puck_shaped_blob():
    rr = load("g2_goal_run_report")
    lines = rr.picture_lines([{"time": "10:34:39", "file": "a01_quick03.jpg", "look_s": 1.2, "circle": {"arc": 1}, "tub": {"claw_in": 11.1, "bearing_deg": -4.7, "width_px": 80}, "floor_puck": None, "tub_puck": {"count": 53, "width_px": 9, "height_px": 7}}])
    assert "11.1 in" in lines[0] and "80 px" in lines[0] and "53 px" in lines[0] and "arc 1" in lines[0]
    img = np.full((240, 240, 3), 100, dtype=np.uint8)
    img[110:120, 120:132] = (170, 100, 80)                                                            # 12 by 10, strongly coloured
    img[80:84, 20:60] = (170, 100, 80)                                                                # a thin strip (tape): not puck-shaped
    blobs = rr.puck_like_blobs(img)
    assert len(blobs) == 1 and blobs[0][1] == 12 and blobs[0][2] == 10


def test_the_finder_regress_tool_reads_a_picture_scores_a_set_and_compares_snapshots():
    fr = load("g2_finder_regress")
    img = np.full((240, 240, 3), 90, dtype=np.uint8)
    img[88:91, 96:140] = (240, 115, 105)                                                              # the tape: a tub about 24 inches off
    r = fr.read_picture(img)
    assert r["tub"] is not None and 20 < r["tub"][0] < 26 and r["inside"] is None
    assert fr.read_picture(np.full((240, 240, 3), 90, dtype=np.uint8))["tub"] is None
    readings = {"shot_001": {"tub": [16.0, 0.0, 58], "puck": None, "inside": None}, "shot_002": {"tub": [9.8, 0.0, 89], "puck": None, "inside": [80, 10, 10]}, "shot_003": {"tub": None, "puck": None, "inside": None}}
    labels = {"shot_001": {"label": "tub_empty", "distance_in": 17.0}, "shot_002": {"label": "tub_8in_inside_middle", "distance_in": 8.0}, "shot_003": {"label": "tub_empty", "distance_in": 20.0}}
    j = fr.judge_set(readings, labels)
    assert j["tub_found"] == 2 and j["inside_expected"] == 1 and j["inside_read"] == 1 and j["inside_false"] == [] and abs(j["mean_error_in"] - 0.4) < 1e-9
    readings["shot_001"]["inside"] = [20, 8, 8]                                                       # an empty tub read as having a puck
    assert fr.judge_set(readings, labels)["inside_false"][0][0] == "shot_001"
    new = {**readings, "shot_002": {"tub": [9.8, 0.0, 89], "puck": None, "inside": None}}
    assert [d[0] for d in fr.compare(readings, new)] == ["shot_002"] and fr.compare(readings, readings) == []
