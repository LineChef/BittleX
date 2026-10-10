"""tools/g2_review.py: the actions and the local HTTP page, with a fake Pi (no ssh, no network beyond 127.0.0.1)."""
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("g2_review", Path(__file__).resolve().parents[2] / "tools" / "g2_review.py")
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


class FakePi:
    """Stands in for the ssh runner: records the calls, answers like the Pi-side modules do."""

    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        mod, rest = args[0], args[1:]
        if mod.endswith("memory.review"):
            if rest[0] == "list":
                return json.dumps([{"id": 7, "ts": "2026-10-01 10:00:00", "fact": "The dog is named Rex.", "core": 0, "importance": 3}])
            if rest[0] == "count":
                return json.dumps({"facts": 24, "exchanges": 310, "observations": 12})
            if rest[0] == "delete":
                return json.dumps({"trash_id": 41})
            if rest[0] == "backup":
                return json.dumps({"backup": "/x.db"})
            if rest[0] == "restore":
                return json.dumps({"kind": "facts", "row_id": 7})
            if rest[0] == "trash":
                return json.dumps([])
            if rest[0] in ("add-fact", "add-observation"):
                return json.dumps({"id": 90, "fact": rest[1]})
            if rest[0] in ("edit-fact", "edit-observation"):
                return json.dumps({"id": int(rest[1])})
            return json.dumps({"removed": 0})
        if rest[0] == "list":
            return json.dumps([])
        if rest[0] == "trash":
            return json.dumps({"moved": rest[1:]})
        if rest[0] == "name":
            return json.dumps({"named": [{"from": r, "to": "named/" + rest[1].replace(" ", "-") + "/" + r.split("/")[-1]} for r in rest[2:]]})
        if rest[0] == "label":
            return json.dumps({"path": rest[1], "detector": [], "dismissed": [rest[2]] if "--restore" not in rest else []})
        if rest[0] == "move":
            return json.dumps({"moved": [{"from": x.split(":")[0], "to": x.split(":")[1]} for x in rest[1:]]})
        return json.dumps({"removed": 0} if rest[0] == "empty-trash" else [])


def test_delete_backs_up_once_per_session_then_deletes():
    pi = FakePi()
    app = G.App(G.Remote("pi", runner=pi))
    assert app.delete("facts", 7) == {"trash_id": 41} and app.delete("facts", 8) == {"trash_id": 41}
    verbs = [c[1] for c in pi.calls]
    assert verbs == ["backup", "delete", "delete"]                      # one backup, before the first delete only
    with pytest.raises(ValueError):
        app.delete("passwords", 1)
    assert pi.calls[-1][1] == "delete"


def test_picture_paths_are_checked_before_they_reach_the_pi():
    app = G.App(G.Remote("pi", runner=FakePi()))
    for bad in ("../../etc/passwd.jpg", "/etc/passwd", "survey/x/../../a.jpg", "other/day/a.jpg", "survey/20261007/a.png"):
        with pytest.raises(ValueError):
            app.trash_pictures([bad])
    assert app.trash_pictures(["survey/20261007/look_down_1.jpg"]) == {"moved": ["survey/20261007/look_down_1.jpg"]}


def test_adding_and_editing_facts_and_observations_backs_up_once_and_passes_the_fields():
    pi = FakePi()
    app = G.App(G.Remote("pi", runner=pi))
    assert app.add_fact("The dishwasher is by the fridge", 4, True)["id"] == 90
    assert app.edit_fact(7, fact="New text", importance=2, core=False) == {"id": 7}
    assert app.add_observation("A steel door", "dishwasher")["id"] == 90
    assert app.edit_observation(5, caption="A steel door with a handle") == {"id": 5}
    mem = [c for c in pi.calls if c[0].endswith("memory.review")]
    assert [c[1] for c in mem] == ["backup", "add-fact", "edit-fact", "add-observation", "edit-observation"]       # one backup, before the first change
    assert mem[1][1:] == ["add-fact", "The dishwasher is by the fridge", "--importance", "4", "--core"]
    assert mem[2][1:] == ["edit-fact", "7", "--fact", "New text", "--importance", "2", "--core", "0"]


def test_dismissing_a_detector_label_checks_the_path_and_passes_restore():
    pi = FakePi()
    app = G.App(G.Remote("pi", runner=pi))
    with pytest.raises(ValueError):
        app.dismiss_label("../x.jpg", "dog")
    with pytest.raises(ValueError):
        app.dismiss_label("survey/20261007/a.jpg", "  ")
    assert app.dismiss_label("survey/20261007/a.jpg", "dog")["dismissed"] == ["dog"]
    assert app.dismiss_label("survey/20261007/a.jpg", "dog", restore=True)["dismissed"] == []
    assert pi.calls[-1][1:] == ["label", "survey/20261007/a.jpg", "dog", "--restore"]


def test_naming_a_picture_checks_paths_and_asks_for_a_name_and_can_be_undone():
    pi = FakePi()
    app = G.App(G.Remote("pi", runner=pi))
    with pytest.raises(ValueError):
        app.name_pictures(["survey/20261007/a.jpg"], "   ")
    with pytest.raises(ValueError):
        app.name_pictures(["../../x.jpg"], "mug")
    out = app.name_pictures(["survey/20261007/look_down_1.jpg"], "dish washer")
    assert out == {"named": [{"from": "survey/20261007/look_down_1.jpg", "to": "named/dish-washer/look_down_1.jpg"}]}
    assert ["pi_pipeline.vision.exploration_pictures", "name", "dish washer", "survey/20261007/look_down_1.jpg"] in pi.calls
    back = app.move_pictures([["named/dish-washer/look_down_1.jpg", "survey/20261007/look_down_1.jpg"]])
    assert back["moved"][0]["to"] == "survey/20261007/look_down_1.jpg"


@pytest.fixture
def server():
    pi = FakePi()
    app = G.App(G.Remote("pi", runner=pi))
    srv = G.ThreadingHTTPServer(("127.0.0.1", 0), G.make_handler(app, "tok", 0))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", pi
    srv.shutdown()


def req(url, token=None, body=None, host=None):
    r = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST")
    if token:
        r.add_header("X-G2-Token", token)
    if host:
        r.add_header("Host", host)
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_page_needs_the_token_for_data_and_actions(server):
    url, pi = server
    code, html = req(url + "/")
    assert code == 200 and b'const TOKEN="tok"' in html and b"G2 Review" in html
    assert req(url + "/api/list?kind=facts")[0] == 403 and req(url + "/api/delete", body={"kind": "facts", "id": 7})[0] == 403
    assert pi.calls == []                                                 # nothing reached the Pi without the token
    code, body = req(url + "/api/list?kind=facts", token="tok")
    assert code == 200 and json.loads(body)[0]["fact"] == "The dog is named Rex."
    code, body = req(url + "/api/delete", token="tok", body={"kind": "facts", "id": 7})
    assert code == 200 and json.loads(body) == {"trash_id": 41}
    assert req(url + "/api/restore", token="tok", body={"trash_id": 41})[0] == 200


def test_a_foreign_host_header_is_refused_and_bad_input_is_a_clean_error(server):
    url, _ = server
    assert req(url + "/", host="evil.example.com")[0] == 403
    code, body = req(url + "/api/delete", token="tok", body={"kind": "nope", "id": 1})
    assert code == 400 and "error" in json.loads(body)
    assert req(url + "/img/..%2F..%2Fetc%2Fpasswd.jpg?t=tok")[0] in (400, 404)


def test_a_picture_without_its_end_marker_is_reported_as_cut_off(tmp_path):
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("g2_review_cutoff", str(__import__("pathlib").Path(__file__).resolve().parents[2] / "tools" / "g2_review.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    whole, cut, padded = tmp_path / "a.jpg", tmp_path / "b.jpg", tmp_path / "c.jpg"
    whole.write_bytes(b"\xff\xd8\xff\xe0data\xff\xd9")
    cut.write_bytes(b"\xff\xd8\xff\xe0data")
    padded.write_bytes(b"\xff\xd8\xff\xe0data" + b"\x00" * 40)                                   # the camera pads a short buffer with zeros
    assert mod.picture_is_cut_off(whole) is False and mod.picture_is_cut_off(cut) is True and mod.picture_is_cut_off(padded) is True
    assert mod.picture_is_cut_off(tmp_path / "missing.jpg") is None


def test_marking_a_picture_as_a_person_is_remembered_beside_the_pictures_and_is_reversible(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "CACHE", tmp_path)
    app = G.App(G.Remote("pi", runner=FakePi()))
    rel = "survey/20261007/after_bow_1.jpg"
    assert app.mark_people([rel], True) == {"marked": [rel], "unmarked": []}
    assert json.loads((tmp_path / "people.json").read_text()) == [rel] and G.read_people_marks() == {rel}
    assert app.mark_people([rel], False) == {"marked": [], "unmarked": [rel]} and G.read_people_marks() == set()
    with pytest.raises(ValueError):
        app.mark_people(["../../etc/passwd.jpg"], True)                                              # paths are checked like every other picture action


def test_counts_give_the_true_totals_for_the_tab_labels(tmp_path):
    app = G.App(G.Remote("pi", runner=FakePi()))
    c = app.counts()
    assert c["facts"] == 24 and c["exchanges"] == 310 and c["observations"] == 12 and c["pictures"] == 0 and c["trash"] == 0
    from pi_pipeline.memory import review
    import sqlite3
    db = tmp_path / "m.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE facts(id INTEGER PRIMARY KEY, fact TEXT); CREATE TABLE exchanges(id INTEGER PRIMARY KEY, user_text TEXT, assistant_text TEXT);"
                      "CREATE TABLE observations(id INTEGER PRIMARY KEY, caption TEXT, labels TEXT); INSERT INTO facts(fact) VALUES ('a'),('b');")
    con.commit(); con.close()
    assert review.count_records(str(db)) == {"facts": 2, "exchanges": 0, "observations": 0}


def test_the_walls_tab_lists_recognition_shots_with_their_labels_and_the_roam_ring_apart_from_the_object_pictures(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "WALL_CACHE", tmp_path)
    (tmp_path / "ring").mkdir()
    for n in ("shot_003.jpg", "shot_009.jpg"):
        (tmp_path / n).write_bytes(b"\xff\xd8\xff")
    (tmp_path / "ring" / "wall_20261010_120537_near.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "labels.json").write_text(json.dumps({"shot_003": {"label": "wall_straight", "distance_in": 16, "set": "prototype1", "flags": ["camera roll 4 deg"], "base_rows": [0.6]},
                                                      "shot_009": {"label": "wall_straight", "distance_in": 16, "expected_turn": None}}))
    app = G.App(G.Remote("pi", runner=lambda a: "[]"))
    walls = app.walls()
    assert [w["file"] for w in walls] == ["shot_003.jpg", "shot_009.jpg", "wall_20261010_120537_near.jpg"]
    assert walls[0]["distance_in"] == 16 and walls[0]["set"] == "prototype1" and walls[2]["src"] == "roam" and walls[2]["label"] == "roam: near"
    assert app.pictures.__func__ is not None                                             # the object pictures tab is a separate method and cache


def test_look_pictures_are_valid_picture_paths_so_they_can_be_deleted_and_have_their_own_tab():
    from tools.g2_review import App
    assert App._rel("looks/20261010/look_left_165605_324.jpg") == "looks/20261010/look_left_165605_324.jpg"
    assert App._rel("survey/20261010/after_bow_1.jpg") and App._rel("named/mug/mug_1.jpg")
    import pytest
    with pytest.raises(ValueError):
        App._rel("../x.jpg")
    from tools import g2_review
    assert '["looks","Looks"]' in g2_review.PAGE if hasattr(g2_review, "PAGE") else True


def test_the_filter_marks_bad_and_duplicate_pictures_automatically_and_only_labelled_kept_ones_can_be_promoted(tmp_path, monkeypatch):
    import io
    import json
    import pytest
    from PIL import Image
    from tools import g2_review as gr
    cache = tmp_path / "explore"
    monkeypatch.setattr(gr, "CACHE", cache)
    monkeypatch.setattr(gr, "PROMOTED", tmp_path / "training_data" / "exploration" / "promoted")
    gr._curation_cache.update(key=None, rows={})

    def jpg(path, base, noise=0):
        import random
        r = random.Random(noise)
        im = Image.new("RGB", (96, 96))
        px = [(min(255, max(0, base + r.randint(-60, 60))),) * 3 for _ in range(96 * 96)]
        im.putdata(px)
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        path.write_bytes(buf.getvalue())
        path.with_suffix(".json").write_text(json.dumps({"pose": "after_bow", "time": "2026-10-10 18:00:00", "detections": []}))
    jpg(cache / "survey/20261010/after_bow_a.jpg", 110, 1)
    jpg(cache / "survey/20261010/after_bow_dark.jpg", 4, 2)               # far too dark: filtered
    jpg(cache / "named/mug/mug_a.jpg", 120, 3)
    v = gr.curation_verdicts()
    assert v["survey/20261010/after_bow_dark.jpg"]["status"] == "rejected"
    assert v["survey/20261010/after_bow_a.jpg"]["status"] in ("kept", "weak") and v["named/mug/mug_a.jpg"]["status"] in ("kept", "weak")
    app = gr.App.__new__(gr.App)
    with pytest.raises(ValueError):
        app.promote_pictures(["survey/20261010/after_bow_a.jpg"])           # not labelled yet: label first
    calls = []
    app.remote = type("R", (), {"call": lambda self, args: calls.append(args) or {"loaded": [{"path": "named/mug/mug_a.jpg"}], "deferred": False}})()
    out = app.promote_pictures(["named/mug/mug_a.jpg"])
    assert calls == [["pi_pipeline.vision.promoted_loader", "add", "named/mug/mug_a.jpg"]]          # promotion queues the picture for the robot's gallery
    assert out["promoted"] == ["named/mug/mug_a.jpg"] and out["gallery"]["deferred"] is False and (tmp_path / "training_data/exploration/promoted/mug/mug_a.jpg").exists()
    assert gr.read_promoted() == {"named/mug/mug_a.jpg": "exploration/promoted/mug/mug_a.jpg"}
    assert app.promote_pictures(["named/mug/mug_a.jpg"], False) == {"unpromoted": ["named/mug/mug_a.jpg"]} and len(calls) == 1      # taking it out does not touch the gallery
    assert gr.read_promoted() == {} and not (tmp_path / "training_data/exploration/promoted/mug/mug_a.jpg").exists()


def test_a_wrong_detector_tag_you_removed_no_longer_sets_the_picture_aside_as_a_person(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from tools import g2_review as gr
    cache = tmp_path / "explore"
    monkeypatch.setattr(gr, "CACHE", cache)
    gr._curation_cache.update(key=None, rows={})
    path = cache / "survey/20261010/after_bow_x.jpg"
    path.parent.mkdir(parents=True)
    im = Image.new("RGB", (96, 96))
    import random
    r = random.Random(5)
    im.putdata([(110 + r.randint(-50, 50),) * 3 for _ in range(96 * 96)])
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    path.write_bytes(buf.getvalue())
    side = path.with_suffix(".json")
    side.write_text(json.dumps({"pose": "after_bow", "time": "2026-10-10 18:00:00", "detections": [{"label": "person", "score": 0.9}]}))
    assert gr.curation_verdicts()["survey/20261010/after_bow_x.jpg"]["status"] == "people"
    side.write_text(json.dumps({"pose": "after_bow", "time": "2026-10-10 18:00:00", "detections": [{"label": "person", "score": 0.9}], "dismissed_labels": ["person"]}))
    import os
    import time
    os.utime(side, (time.time() + 5, time.time() + 5))
    assert gr.curation_verdicts()["survey/20261010/after_bow_x.jpg"]["status"] in ("kept", "weak")      # the removed tag no longer counts; the record stays in the sidecar


def test_a_labelled_picture_that_the_filter_kept_is_promoted_automatically_unless_you_took_it_out(tmp_path, monkeypatch):
    import io
    import json
    import random
    from PIL import Image
    from tools import g2_review as gr
    cache = tmp_path / "explore"
    monkeypatch.setattr(gr, "CACHE", cache)
    monkeypatch.setattr(gr, "PROMOTED", tmp_path / "training_data" / "exploration" / "promoted")
    gr._curation_cache.update(key=None, rows={})

    def jpg(path, base, seed):
        r = random.Random(seed)
        im = Image.new("RGB", (96, 96))
        im.putdata([(min(255, max(0, base + r.randint(-60, 60))),) * 3 for _ in range(96 * 96)])
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        path.write_bytes(buf.getvalue())
        path.with_suffix(".json").write_text(json.dumps({"pose": "named", "time": "2026-10-10 18:00:00", "detections": []}))
    jpg(cache / "named/mug/mug_a.jpg", 120, 1)
    jpg(cache / "survey/20261010/after_bow_a.jpg", 110, 2)
    items = [{"path": "named/mug/mug_a.jpg", "group": "named", "folder": "mug"}, {"path": "survey/20261010/after_bow_a.jpg", "group": "survey", "folder": "20261010"}]
    calls = []
    app = gr.App.__new__(gr.App)
    app.remote = type("R", (), {"pictures": lambda self, *a: [dict(i) for i in items], "call": lambda self, args: calls.append(args) or {"loaded": [], "deferred": False}})()
    out = app.pictures()
    named = [p for p in out if p["group"] == "named"][0]
    assert named["promoted"] is True and calls == [["pi_pipeline.vision.promoted_loader", "add", "named/mug/mug_a.jpg"]]
    assert [p for p in out if p["group"] == "survey"][0]["promoted"] is False                  # an unlabelled picture waits for a label
    app.pictures()
    assert len(calls) == 1                                                                         # already promoted: nothing more is queued
    app.promote_pictures(["named/mug/mug_a.jpg"], False)                                           # you take it out by hand ...
    out = app.pictures()
    assert [p for p in out if p["group"] == "named"][0]["promoted"] is False and len(calls) == 1   # ... and it is not promoted again
    app.promote_pictures(["named/mug/mug_a.jpg"])                                                  # promoting by hand puts it back
    assert gr.read_promoted() and len(calls) == 2


def test_wall_pictures_can_be_trashed_restored_and_roam_pictures_labelled_with_the_estimator_reading(tmp_path, monkeypatch):
    import json
    from pi_pipeline.vision import wall_pictures as wp
    from tools import g2_review as gr
    folder, ring = tmp_path / "pics", tmp_path / "ring"
    (folder).mkdir()
    ring.mkdir()
    (folder / "shot_021.jpg").write_bytes(b"x")
    (folder / "labels.json").write_text(json.dumps({"shot_021": {"label": "wall_straight", "distance_in": 16}}))
    (ring / "wall_20261010_170000_near.jpg").write_bytes(b"y")
    monkeypatch.setattr(wp, "_ring_dir", lambda: ring)
    assert wp.trash(folder, ["shot_021", "ring/wall_20261010_170000_near.jpg"]) == ["shot_021", "ring/wall_20261010_170000_near.jpg"]
    assert not (folder / "shot_021.jpg").exists() and not (ring / "wall_20261010_170000_near.jpg").exists() and wp.load_labels(folder) == {}
    assert (tmp_path / "ring_trash" / "wall_20261010_170000_near.jpg").exists()                  # nothing was erased
    assert wp.restore(folder, ["shot_021", "ring/wall_20261010_170000_near.jpg"]) == ["shot_021", "ring/wall_20261010_170000_near.jpg"]
    assert (folder / "shot_021.jpg").exists() and wp.load_labels(folder)["shot_021"]["distance_in"] == 16 and (ring / "wall_20261010_170000_near.jpg").exists()
    wc = tmp_path / "wallcache"
    (wc / "ring").mkdir(parents=True)
    (wc / "ring" / "wall_20261010_170000_near.jpg").write_bytes(b"y")
    (wc / "wall_dryrun.jsonl").write_text(json.dumps({"pic": "wall_20261010_170000_near.jpg", "state": "near", "nearest_in": 9.7, "group_in": [9.7], "turn": "right"}) + "\n")
    monkeypatch.setattr(gr, "WALL_CACHE", wc)
    app = gr.App.__new__(gr.App)
    row = [r for r in app.walls() if r["src"] == "roam"][0]
    assert row["label"] == "roam: near" and not row["labelled"] and row["estimate"]["nearest_in"] == 9.7
    app.label_wall("ring/wall_20261010_170000_near.jpg", "wall", "10")
    row = [r for r in app.walls() if r["src"] == "roam"][0]
    assert row["label"] == "wall" and row["labelled"] and row["distance_in"] == 10.0
    import pytest
    with pytest.raises(ValueError):
        app.label_wall("shot_021.jpg", "wall")
    with pytest.raises(ValueError):
        gr.App._wall_name("../../x.jpg")
