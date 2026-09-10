"""A tiny local web UI to browse / prune G2's memory.

Single file, stdlib only (`http.server`), no deps -- runs anywhere the rest of
`pi_pipeline` does. Facts list with add / delete, a searchable conversation log,
a `recall()` preview, and a wipe button.

    python -m pi_pipeline.memory.webui              # http://127.0.0.1:8899
    python -m pi_pipeline.memory.webui --port 9000 --db /path/to/g2_memory.db

Binds to 127.0.0.1 only -- this is the household's conversation history; keep it
on the machine. No auth (local tool); wipe needs the confirm checkbox.
"""
from __future__ import annotations

import argparse
import html
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..config import settings
from .memory import Memory
from .store import Store

_CSS = """
:root{color-scheme:light dark}
body{font:15px/1.5 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}
h1{font-size:1.3rem} h2{font-size:1.05rem;margin-top:2rem;border-bottom:1px solid #8884;padding-bottom:.3rem}
form{margin:.5rem 0} input[type=text]{width:60%;padding:.35rem} button{padding:.35rem .7rem;cursor:pointer}
ul{list-style:none;padding:0} li{padding:.35rem 0;border-bottom:1px solid #8882;display:flex;gap:.6rem;align-items:baseline}
li .meta{color:#8889;font-size:.85em;white-space:nowrap}
.ex{padding:.5rem 0;border-bottom:1px solid #8882} .ex .you{font-weight:600} .ex .g2{color:#8ac}
.danger{color:#b00} pre{white-space:pre-wrap;background:#8881;padding:.7rem;border-radius:6px}
.empty{color:#8889;font-style:italic}
"""


def _page(store: Store, *, q: str = "", recall_q: str = "") -> str:
    facts = store.list_facts()
    fact_items = "".join(
        f"<li><form method=post action=/forget style=margin:0>"
        f"<input type=hidden name=id value={r['id']}>"
        f"<button class=danger title='delete'>×</button></form>"
        f"<span>{html.escape(r['fact'])}</span>"
        f"<span class=meta>#{r['id']} · {r['ts'][:10]}"
        + (f" · recalled {r['last_recalled'][:10]}" if r['last_recalled'] else "")
        + "</span></li>"
        for r in facts
    ) or "<li class=empty>no facts yet</li>"

    results = ""
    if q:
        rows = store.search_exchanges(q, limit=25)
        results = "".join(
            f"<div class=ex><div class=you>you: {html.escape(r['user_text'])}</div>"
            f"<div class=g2>g2: {html.escape(r['assistant_text'])}</div>"
            f"<div class=meta>{r['ts'][:19]}"
            + (f" · [{html.escape(r['actions'])}]" if r['actions'] else "") + "</div></div>"
            for r in rows
        ) or "<p class=empty>no matches</p>"
    else:
        rows = store.recent_exchanges(15)
        results = "".join(
            f"<div class=ex><div class=you>you: {html.escape(r['user_text'])}</div>"
            f"<div class=g2>g2: {html.escape(r['assistant_text'])}</div>"
            f"<div class=meta>{r['ts'][:19]}</div></div>"
            for r in reversed(rows)
        ) or "<p class=empty>no conversation logged yet</p>"

    recall_box = ""
    if recall_q:
        ctx = Memory(settings).recall(recall_q)
        recall_box = f"<pre>{html.escape(ctx) if ctx else '(nothing would be injected)'}</pre>"

    n_ex = store.exchange_count()
    return f"""<!doctype html><meta charset=utf-8><title>G2 memory</title>
<meta name=viewport content='width=device-width,initial-scale=1'>
<style>{_CSS}</style>
<h1>G2 memory <span class=meta>{len(facts)} facts · {n_ex} exchanges</span></h1>

<h2>Facts</h2>
<ul>{fact_items}</ul>
<form method=post action=/add>
  <input type=text name=fact placeholder='a durable fact to remember' required>
  <button>add</button>
</form>

<h2>Conversation log</h2>
<form method=get action=/>
  <input type=text name=q value="{html.escape(q)}" placeholder='search the log (FTS)'>
  <button>search</button> {'<a href=/>clear</a>' if q else ''}
</form>
{results}

<h2>recall() preview</h2>
<form method=get action=/>
  <input type=text name=recall_q value="{html.escape(recall_q)}" placeholder='what would recall() inject for this input?'>
  <button>preview</button>
</form>
{recall_box}

<h2 class=danger>Wipe</h2>
<form method=post action=/wipe onsubmit="return confirm('Delete ALL facts and exchanges? This cannot be undone.')">
  <label><input type=checkbox name=confirm value=yes required> I understand this deletes everything</label>
  <button class=danger>wipe memory</button>
</form>
"""


class _Handler(BaseHTTPRequestHandler):
    db_path = ""

    def _store(self) -> Store:
        return Store(self.db_path)

    def _send_html(self, body: str, code: int = 200):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, to: str = "/"):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != "/":
            self._send_html("<h1>404</h1>", 404)
            return
        qs = urllib.parse.parse_qs(u.query)
        st = self._store()
        try:
            self._send_html(_page(st, q=qs.get("q", [""])[0],
                                  recall_q=qs.get("recall_q", [""])[0]))
        finally:
            st.close()

    def _form(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode()
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        f = self._form()
        st = self._store()
        try:
            if u.path == "/add":
                if f.get("fact"):
                    st.add_fact(f["fact"])
            elif u.path == "/forget":
                if f.get("id"):
                    st.forget_fact(f["id"])
            elif u.path == "/wipe":
                if f.get("confirm") == "yes":
                    st.wipe()
            else:
                self._send_html("<h1>404</h1>", 404)
                return
        finally:
            st.close()
        self._redirect("/")


def serve(db_path: str, host: str = "127.0.0.1", port: int = 8899) -> None:
    _Handler.db_path = db_path
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"G2 memory UI  ->  http://{host}:{port}   (db: {db_path})   Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.memory.webui")
    ap.add_argument("--db", default=settings.memory_db_path)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8899)
    a = ap.parse_args()
    serve(a.db, a.host, a.port)


if __name__ == "__main__":
    main()
