"""tools/g2_wall_recal.py: the comparison rule, set lookup and refusals."""
import importlib.util
import os
import subprocess
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
_spec = importlib.util.spec_from_file_location("g2_wall_recal_under_test", os.path.join(_TOOLS, "g2_wall_recal.py"))
wr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wr)

FA = "false alarms (labelled nothing, acted on)"


def sc(fa, w12="2 of 2", w24="2 of 2"):
    return {"wall acted on": {"within 12 in": w12, "13 to 24 in": w24, "farther than 24 in": "0 of 1"}, FA: f"{fa} of 59", "false alarm shots": []}


def test_the_candidate_must_cut_false_alarms_without_missing_a_wall():
    assert wr.verdict(sc(30), sc(5)).startswith("BETTER")
    assert wr.verdict(sc(30), sc(30)).startswith("SAME")
    assert wr.verdict(sc(5), sc(30)).startswith("WORSE")
    assert wr.verdict(sc(30), sc(2, w12="1 of 2")).startswith("TRADE")             # fewer false alarms but a wall within 12 in is missed: never reported as a win


def test_counts_parse_and_a_missing_set_is_refused(tmp_path):
    assert wr.count("3 of 5") == (3, 5) and wr.count("none") == (0, 0)
    r = subprocess.run([sys.executable, os.path.join(_TOOLS, "g2_wall_recal.py"), "no-such-set-xyz"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "."})
    assert r.returncode != 0 and "no calibration set" in r.stderr
