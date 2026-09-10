import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from pi_pipeline.memory.store import Store
from pi_pipeline.memory.webui import _Handler, _page


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "mem.db")
    s = Store(p)
    s.add_fact("the user prefers cheap iteration over big runs")
    s.add_fact("G2 lives on the user's desk")
    s.log_exchange("what's the weather", "I can't check that, sorry", [])
    s.log_exchange("do a happy wiggle", "wiggling now", ["happy_wiggle"])
    s.close()
    return p


def test_page_renders_facts_and_log(db):
    body = _page(Store(db))
    assert "the user prefers cheap iteration" in body
    assert "G2 lives on the user" in body
    assert "do a happy wiggle" in body
    assert "2 facts" in body and "2 exchanges" in body


def test_page_search_filters_the_log(db):
    body = _page(Store(db), q="wiggle")
    assert "do a happy wiggle" in body
    assert "what&#x27;s the weather" not in body and "weather" not in body


def test_page_escapes_html(tmp_path):
    p = str(tmp_path / "x.db")
    s = Store(p); s.add_fact("watch out for <script>alert(1)</script> injection"); s.close()
    body = _page(Store(p))
    assert "<script>alert(1)" not in body
    assert "&lt;script&gt;" in body


def test_recall_preview_block(db):
    body = _page(Store(db), recall_q="desk")
    assert "<pre>" in body


# --- a live server round-trip -------------------------------------------------
@pytest.fixture
def server(db):
    _Handler.db_path = db
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=3) as r:
        return r.status, r.read().decode()


def _post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 method="POST")
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.status, r.read().decode()




def test_index_serves(server):
    code, body = _get(server + "/")
    assert code == 200 and "G2 memory" in body


def test_add_then_delete_fact_via_http(server, db):
    _post(server + "/add", {"fact": "added through the web ui"})
    assert any(r["fact"] == "added through the web ui" for r in Store(db).list_facts())
    fid = [r["id"] for r in Store(db).list_facts() if r["fact"] == "added through the web ui"][0]
    _post(server + "/forget", {"id": str(fid)})
    assert not any(r["fact"] == "added through the web ui" for r in Store(db).list_facts())


def test_wipe_requires_the_confirm_field(server, db):
    _post(server + "/wipe", {"confirm": "no"})          # not confirmed
    assert Store(db).exchange_count() == 2
    _post(server + "/wipe", {"confirm": "yes"})
    assert Store(db).exchange_count() == 0 and Store(db).list_facts() == []


def test_unknown_path_404s(server):
    import urllib.error
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(server + "/nope")
    assert e.value.code == 404
