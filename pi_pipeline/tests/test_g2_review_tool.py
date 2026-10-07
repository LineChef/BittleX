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
            if rest[0] == "delete":
                return json.dumps({"trash_id": 41})
            if rest[0] == "backup":
                return json.dumps({"backup": "/x.db"})
            if rest[0] == "restore":
                return json.dumps({"kind": "facts", "row_id": 7})
            if rest[0] == "trash":
                return json.dumps([])
            return json.dumps({"removed": 0})
        if rest[0] == "list":
            return json.dumps([])
        if rest[0] == "trash":
            return json.dumps({"moved": rest[1:]})
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
