"""The "Identify new objects" goal: scoring a roam from what it left behind, the knobs, the stop, and the in-service readiness check (user, 2026-11-06)."""
import json
import os
import time

import pytest

from pi_pipeline.goals import discover, inprocess, spec
from pi_pipeline.goals.approach import AttemptContext, AttemptResult, make


def _pic(root, kind_dir, name, *, mean=110, clip=0.01, labels=(), kind="survey", place=None, mtime=None):
    d = root / kind_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jpg").write_bytes(b"x")
    (d / f"{name}.json").write_text(json.dumps({"kind": kind, "exposure": {"mean": mean, "clip_high": clip}, "detections": [{"label": x} for x in labels], "place": place}))
    if mtime:
        os.utime(d / f"{name}.json", (mtime, mtime))


def test_the_goal_exists_with_the_ten_minute_budget_and_both_attachments():
    g = spec.load()[0]["discover_objects"]
    assert g.title == "Identify new objects" and g.attempts == 3 and g.minutes == 10.5 and g.needs_attachment is None and "find new objects" in g.start_words
    ap = make("discover_objects")
    assert {k.name for k in ap.knobs()} == set(discover.SPEC) and ap.base_settings()["roam_s"] == 180
    assert 3 * ap.base_settings()["roam_s"] <= g.minutes * 60                       # three roams fit the ten minutes


def test_pictures_since_counts_usable_survey_pictures_and_leaves_looks_and_people_out(tmp_path):
    now = time.time()
    _pic(tmp_path, "survey/20261106", "a", place="kitchen")
    _pic(tmp_path, "survey/20261106", "dark", mean=10)
    _pic(tmp_path, "survey/20261106", "blown", clip=0.6)
    _pic(tmp_path, "survey/20261106", "p", labels=("person",))
    _pic(tmp_path, "looks/20261106", "l", kind="look_left")
    _pic(tmp_path, "survey/20261106", "old", mtime=now - 3600)
    got = {p["file"]: p for p in discover.pictures_since(now - 60, tmp_path)}
    assert set(got) == {"a.jpg", "dark.jpg", "blown.jpg", "p.jpg"}
    assert got["a.jpg"]["usable"] and got["a.jpg"]["place"] == "kitchen" and not got["dark.jpg"]["usable"] and not got["blown.jpg"]["usable"] and got["p.jpg"]["people"] and not got["p.jpg"]["usable"]


def _score(extra, ended="time limit"):
    return make("discover_objects").score(AttemptResult(ended, 100.0, [], extra), {})


def test_a_roam_is_scored_from_what_it_left_in_the_gallery_and_the_pictures():
    ok = _score({"new_candidates": 1, "usable": 4, "pictures": 5})
    assert ok.code == "new_object" and ok.success and ok.score == 1.0 and ok.stages == {"find": 1.0}
    assert _score({"new_candidates": 1, "usable": 2, "pictures": 3}).code == "few_pictures"
    assert _score({"new_candidates": 0, "usable": 3, "pictures": 3}).code == "nothing_new"
    assert _score({"new_candidates": 0, "usable": 0, "pictures": 0}).code == "never_found"
    assert _score({}, ended="fell").code == "fell"
    stopped = _score({}, ended="voice command")
    assert stopped.code == "stopped" and not stopped.counted


def test_judge_roam_finds_new_and_grown_candidates():
    before = {"a": {"named": False, "samples": 2}, "b": {"named": True, "samples": 5}}
    after = {"a": {"named": False, "samples": 4}, "b": {"named": True, "samples": 7}, "c": {"named": False, "samples": 3}}
    r = discover.judge_roam("time limit", before, after, [{"usable": True, "people": False, "place": "kitchen"}, {"usable": False, "people": True}])
    assert r["new_candidates"] == 1 and r["grown_candidates"] == 1 and r["usable"] == 1 and r["people"] == 1 and r["places"] == ["kitchen"]


def test_an_attempt_runs_the_roam_with_the_knobs_as_settings_and_puts_them_back(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_EXPLORE_PICTURES_DIR", str(tmp_path / "pics"))
    monkeypatch.setattr(discover, "gallery_path", lambda: tmp_path / "gallery.json")
    monkeypatch.delenv("G2_INTEREST_EVERY_S", raising=False)
    seen = {}

    def fake_roam(settings, ctx):
        seen["env"] = os.environ.get("G2_INTEREST_EVERY_S"), os.environ.get("G2_SURVEY_RELAX_S")
        for n in ("a", "b", "c"):
            _pic(tmp_path / "pics", "survey/20261106", n)
        (tmp_path / "gallery.json").write_text(json.dumps({"entries": {"new1": {"name": None, "sample_count": 3}}}))
        return "roam time limit"
    ap = make("discover_objects", run=fake_roam)
    res = ap.run_attempt({"roam_s": 120, "peek_every_s": 6.0, "relax_s": 40}, AttemptContext(say=lambda m: None))
    assert seen["env"] == ("6.0", "40") and os.environ.get("G2_INTEREST_EVERY_S") is None            # applied during the roam, restored after
    out = ap.score(res, {})
    assert out.code == "new_object" and res.extra["usable"] == 3 and res.extra["roam_s"] == 120


def test_a_goal_that_explores_needs_the_service_ready_for_an_exploration(monkeypatch):
    import types
    shared = types.SimpleNamespace(link=object(), camera=object())
    monkeypatch.delenv("G2_EXPLORE_INPROCESS", raising=False)
    ok, why = inprocess.ready(shared, "discover_objects")
    assert not ok and "explor" in why                                                              # the old hand-over is used instead
    assert inprocess.ready(shared, "ball_punt") == (True, "")                                      # the ball goal does not need it
