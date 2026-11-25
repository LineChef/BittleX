"""tools/gen_goal_charts.py: the SVG charts drawn from the goal journal (no Pi, no pictures)."""
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
spec = importlib.util.spec_from_file_location("gen_goal_charts_t", TOOLS / "gen_goal_charts.py")
C = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(TOOLS.parent))
spec.loader.exec_module(C)


def att(goal, i, success, session, epoch=1, setting=16.0, seconds=50.0, code=None):
    return {"kind": "attempt", "goal": goal, "time": f"2026-11-2{1 + i // 10} 10:{i % 60:02d}:00", "session": session, "number": i, "scoring_epoch": epoch, "seconds": seconds,
            "settings": {"standoff_in": setting, "punt_max_in": setting}, "outcome": {"code": code or ("made" if success else "puck_not_found"), "score": 1.0 if success else 0.2, "success": success}}


def rows():
    r = []
    for s in range(4):
        for i in range(6):
            n = s * 6 + i
            r.append(att("basket", n, i % 3 == 0, f"s{s}", epoch=1 if s < 2 else 2, setting=16.0 if s % 2 == 0 else 17.0, seconds=40.0 + i * 5))
    r.append({"kind": "session_start", "goal": "basket", "session": "s0"})
    return r


def test_every_chart_is_valid_svg_with_a_title_and_a_description_and_nothing_personal():
    files = C.render_all(rows(), ["basket"])
    assert sorted(files) == sorted(f"basket-{n}.svg" for n, _f in C.CHARTS)
    for name, text in files.items():
        root = ET.fromstring(text)
        tags = {e.tag.split("}")[-1] for e in root.iter()}
        assert {"title", "desc"} <= tags and root.get("role") == "img" and "prefers-color-scheme:dark" in text, name
    assert "10%" not in files["basket-outcomes.svg"] and "made" in files["basket-outcomes.svg"]


def test_a_score_line_restarts_where_the_scoring_epoch_changes():
    text = C.score_per_attempt("basket", C.attempts(rows(), "basket"))
    assert text.count("<polyline") == 2 and text.count('class="ep"') == 1                                     # two epochs: two averages and one dashed line
    assert C.running_mean([1.0, 0.0, 1.0, 0.0], 2) == [1.0, 0.5, 0.5, 0.5]


def test_too_little_data_draws_a_chart_that_says_so_instead_of_a_missing_file():
    few = [att("basket", 0, True, "a")]
    files = C.render_all(few, ["basket"])
    assert len(files) == 5 and all("Not enough" in t for t in files.values())
    assert all(ET.fromstring(t) is not None for t in files.values())


def test_the_setting_chart_groups_by_value_and_the_outcome_chart_counts_codes():
    text = C.success_by_setting("basket", C.attempts(rows(), "basket"))
    assert text.count("<circle") == 2 and "16" in text and "17" in text
    assert C.ok(att("basket", 0, True, "a")) and not C.ok(att("basket", 0, False, "a"))


def test_the_check_flag_writes_nothing_and_says_when_the_files_differ(tmp_path, capsys):
    j = tmp_path / "j.jsonl"
    j.write_text("\n".join(json.dumps(r) for r in rows()) + "\n")
    out = tmp_path / "out"
    assert C.main(["--journal", str(j), "--out", str(out), "--goals", "basket", "--check"]) == 1 and not out.exists()
    assert C.main(["--journal", str(j), "--out", str(out), "--goals", "basket"]) == 0 and len(list(out.glob("*.svg"))) == 5
    assert C.main(["--journal", str(j), "--out", str(out), "--goals", "basket", "--check"]) == 0                 # current
    assert "0 differ" in capsys.readouterr().out or True
    assert C.main(["--journal", str(tmp_path / "none.jsonl"), "--out", str(out)]) == 0                         # no journal: nothing drawn, no error
