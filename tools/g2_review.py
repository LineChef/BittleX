#!/usr/bin/env python3
"""A review page for G2's memory and saved pictures, with an X on every record.

    g2pimem            # opens this page on the Facts tab (g2pimem <subcommand> still prints text: log 20, search ..., usage)
    g2pics             # opens this page on the Pictures tab (g2pics status / pull still print or copy)
    python3 tools/g2_review.py [--tab facts|exchanges|observations|pictures|trash] [--no-open] [--stop]

The page runs as a background server (so your terminal is free): the first call starts it, later calls just open the browser. `--stop` ends it. Log: ~/g2_logs/review_server.log.

Tabs: Facts, Conversations, Observations (what G2 noticed), Pictures (survey stops and objects you named), Trash. The X moves a record to the Trash
(you get an Undo for a few seconds, and the Trash tab restores anything later); only "Empty trash" deletes for good, and it asks twice. A safe copy of the
memory database is made before the first delete of each session. Everything runs on the Pi through ssh (needs G2_PI, e.g. user@g2pi.local); the pictures
are copied to ~/g2_pictures/explore on this Mac so the page can show them. The page listens on 127.0.0.1 only and every action needs a token that only the
page you opened knows. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CACHE = Path(os.path.expanduser("~/g2_pictures/explore"))
KINDS = ("facts", "exchanges", "observations")


class Remote:
    """The Pi side, over ssh. `runner(args: list[str]) -> str` can be replaced in tests."""

    def __init__(self, pi: str, runner=None):
        self.pi = pi
        self._runner = runner or self._ssh

    def _ssh(self, args: list[str]) -> str:
        cmd = "cd ~/bittleX && pi_pipeline/.venv/bin/python -m " + " ".join(shlex.quote(a) for a in args)
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", self.pi, cmd], capture_output=True, text=True, timeout=120)
        if r.returncode not in (0, 1):
            raise RuntimeError((r.stderr or r.stdout or "ssh failed").strip()[-400:])
        return r.stdout

    def call(self, args: list[str]):
        out = self._runner(args).strip().splitlines()
        if not out:
            raise RuntimeError("the Pi returned nothing")
        data = json.loads(out[-1])
        if isinstance(data, dict) and "error" in data:
            raise ValueError(data["error"])
        return data

    def memory(self, *a):
        return self.call(["pi_pipeline.memory.review", *a])

    def pictures(self, *a):
        return self.call(["pi_pipeline.vision.exploration_pictures", *a])

    def sync_pictures(self) -> str:
        CACHE.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["rsync", "-a", f"{self.pi}:.local/share/g2/explore_pictures/", str(CACHE) + "/"], capture_output=True, text=True, timeout=300)
        return "ok" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["no pictures yet"])[-1]


class App:
    """The actions behind the page. Pure of HTTP, so it can be tested with a fake Remote."""

    def __init__(self, remote: Remote):
        self.remote = remote
        self._backed_up = False

    def list(self, kind: str, q: str = "", limit: int = 300):
        if kind not in KINDS:
            raise ValueError("unknown kind")
        return self.remote.memory("list", kind, "--limit", str(int(limit)), "--query", q)

    def delete(self, kind: str, row_id: int):
        if kind not in KINDS:
            raise ValueError("unknown kind")
        if not self._backed_up:                              # one safe copy of the database before this session's first delete
            self.remote.memory("backup")
            self._backed_up = True
        return self.remote.memory("delete", kind, str(int(row_id)))

    def restore(self, trash_id: int):
        return self.remote.memory("restore", str(int(trash_id)))

    def pictures(self):
        return self.remote.pictures("list")

    def trash_pictures(self, paths: list[str]):
        out = self.remote.pictures("trash", *[self._rel(p) for p in paths])
        for p in paths:                                       # the local copy goes too
            f = CACHE / self._rel(p)
            for g in (f, f.with_suffix(".json")):
                try:
                    g.unlink()
                except OSError:
                    pass
        return out

    def restore_pictures(self, paths: list[str]):
        out = self.remote.pictures("restore", *[self._rel(p) for p in paths])
        self.remote.sync_pictures()
        return out

    def trash(self):
        return {"memory": self.remote.memory("trash"), "pictures": self.remote.pictures("trash-list")}

    def empty_trash(self):
        return {"memory": self.remote.memory("empty-trash"), "pictures": self.remote.pictures("empty-trash")}

    @staticmethod
    def _rel(p: str) -> str:
        if not re.fullmatch(r"(survey|named)/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-.]+\.jpg", p or ""):
            raise ValueError(f"not a picture path: {p!r}")
        return p


def make_handler(app: App, token: str, port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj).encode())

        def _ok_host(self) -> bool:
            return (self.headers.get("Host") or "").split(":")[0] in ("127.0.0.1", "localhost")

        def _authed(self, qs) -> bool:
            return self.headers.get("X-G2-Token") == token or qs.get("t", [""])[0] == token

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if not self._ok_host():
                return self._send(403, b"bad host", "text/plain")
            if u.path == "/ping":
                return self._json({"app": "g2review", "pid": os.getpid()})
            if u.path == "/":
                return self._send(200, PAGE.replace("__TOKEN__", token).encode(), "text/html; charset=utf-8")
            if not self._authed(qs):
                return self._send(403, b"bad token", "text/plain")
            try:
                if u.path.startswith("/img/"):
                    rel = app._rel(urllib.parse.unquote(u.path[5:]))
                    f = CACHE / rel
                    return self._send(200, f.read_bytes(), "image/jpeg") if f.is_file() else self._send(404, b"missing", "text/plain")
                if u.path == "/api/list":
                    return self._json(app.list(qs.get("kind", [""])[0], qs.get("q", [""])[0]))
                if u.path == "/api/pictures":
                    return self._json(app.pictures())
                if u.path == "/api/trash":
                    return self._json(app.trash())
                return self._send(404, b"not found", "text/plain")
            except (ValueError, KeyError) as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if not self._ok_host() or self.headers.get("X-G2-Token") != token:
                return self._send(403, b"bad token", "text/plain")
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if u.path == "/api/delete":
                    return self._json(app.delete(body["kind"], int(body["id"])))
                if u.path == "/api/restore":
                    return self._json(app.restore(int(body["trash_id"])))
                if u.path == "/api/pictures/trash":
                    return self._json(app.trash_pictures(list(body["paths"])))
                if u.path == "/api/pictures/restore":
                    return self._json(app.restore_pictures(list(body["paths"])))
                if u.path == "/api/pictures/sync":
                    return self._json({"sync": app.remote.sync_pictures()})
                if u.path == "/api/empty-trash":
                    return self._json(app.empty_trash())
                return self._send(404, b"not found", "text/plain")
            except (ValueError, KeyError) as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    return Handler


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>G2 Review</title>
<style>
:root{--bg:#f5f7f6;--surface:#fff;--ink:#13201f;--ink2:#46564f;--muted:#76857f;--line:#dde4e1;--accent:#0b6b62;--x:#b83227;--xbg:#fbe5e2;--ok:#18794a}
@media (prefers-color-scheme:dark){:root{--bg:#0f1514;--surface:#172120;--ink:#e9f0ee;--ink2:#b3c1bc;--muted:#869590;--line:#2a3836;--accent:#4fc4b6;--x:#f0746a;--xbg:#3b1a17;--ok:#4fc58a;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:20px 16px 80px}
h1{font-size:1.4rem;margin:0 0 4px}.sub{color:var(--muted);font-size:.85rem;margin-bottom:14px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0}
.tab{border:1px solid var(--line);background:var(--surface);color:var(--ink2);border-radius:6px;padding:6px 12px;cursor:pointer;font:inherit}
.tab[aria-selected=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
.bar{display:flex;gap:8px;align-items:center;margin-bottom:10px}.bar input{flex:1;min-width:0;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink);font:inherit}
button{font:inherit;cursor:pointer}.row{display:flex;gap:10px;align-items:flex-start;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:8px}
.main{flex:1;min-width:0;overflow-wrap:anywhere}.meta{color:var(--muted);font-size:.8rem;margin-top:2px}.q{color:var(--ink2)}
.x{flex:none;width:32px;height:32px;border-radius:6px;border:1px solid var(--line);background:var(--surface);color:var(--x);font-size:1.25rem;line-height:1}.x:hover{background:var(--xbg);border-color:var(--x)}
.btn{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:6px;padding:6px 12px}.btn.danger{color:var(--x);border-color:var(--x)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}.card{position:relative;background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.card img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:#000}.card .cap{padding:6px 8px;font-size:.78rem;color:var(--ink2)}
.card .x{position:absolute;top:6px;right:6px;background:rgba(255,255,255,.85)}.group{margin:16px 0 6px;font-weight:600;color:var(--ink2)}
.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:10px 14px;border-radius:8px;display:none;gap:12px;align-items:center;max-width:90vw}
.toast button{background:none;border:0;color:var(--bg);text-decoration:underline}.empty{color:var(--muted);padding:24px 0}
</style></head><body><div class="wrap">
<h1>G2 Review</h1><div class="sub" id="status">connecting to the Pi…</div>
<div class="tabs" role="tablist" id="tabs"></div>
<div class="bar"><input id="q" type="search" placeholder="Filter this tab"><button class="btn" id="refresh">Refresh</button><span id="extra"></span></div>
<div id="list"></div></div>
<div class="toast" id="toast"><span id="toastmsg"></span><button id="undo">Undo</button></div>
<script>
const TOKEN="__TOKEN__";const TABS=[["facts","Facts"],["exchanges","Conversations"],["observations","Observations"],["pictures","Pictures"],["trash","Trash"]];
let tab=(location.hash||"").replace("#","")||localStorage.getItem("g2tab")||"facts";if(!TABS.some(t=>t[0]===tab))tab="facts",data=[],undoFn=null,timer=null,confirmAt=0;
const $=s=>document.querySelector(s);
async function api(path,body){const o=body===undefined?{headers:{"X-G2-Token":TOKEN}}:{method:"POST",headers:{"X-G2-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify(body)};
 const r=await fetch(path,o);const j=await r.json();if(!r.ok||j.error)throw new Error(j.error||r.statusText);return j}
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
function toast(msg,undo){$("#toastmsg").textContent=msg;undoFn=undo||null;$("#undo").style.display=undo?"":"none";$("#toast").style.display="flex";clearTimeout(timer);timer=setTimeout(()=>$("#toast").style.display="none",9000)}
$("#undo").onclick=async()=>{if(undoFn){try{await undoFn();toast("Restored")}catch(e){toast("Could not restore: "+e.message)}load()}};
function drawTabs(){const t=$("#tabs");t.replaceChildren();for(const [k,n] of TABS){const b=el("button","tab",n);b.setAttribute("role","tab");b.setAttribute("aria-selected",k===tab);b.onclick=()=>{tab=k;localStorage.setItem("g2tab",k);$("#q").value="";drawTabs();load()};t.append(b)}}
function xbtn(fn){const b=el("button","x","×");b.title="Delete (goes to the Trash; you can undo)";b.setAttribute("aria-label","Delete");b.onclick=fn;return b}
function text(r){return r.fact||r.caption||(r.user_text?"You: "+r.user_text:"")}
async function load(){const list=$("#list");$("#extra").replaceChildren();list.replaceChildren(el("div","empty","Loading…"));
 try{
  if(tab==="pictures"){await api("/api/pictures/sync",{});data=await api("/api/pictures")}
  else if(tab==="trash"){data=await api("/api/trash")}
  else{data=await api("/api/list?kind="+tab+"&q="+encodeURIComponent($("#q").value))}
  $("#status").textContent="Connected to the Pi. Deleted records go to the Trash first; nothing is removed for good until you empty it.";
 }catch(e){$("#status").textContent="Problem: "+e.message;list.replaceChildren(el("div","empty",e.message));return}
 render()}
function render(){const list=$("#list"),f=$("#q").value.toLowerCase();list.replaceChildren();
 if(tab==="pictures"){const items=data.filter(p=>!f||JSON.stringify(p).toLowerCase().includes(f));if(!items.length){list.append(el("div","empty","No pictures yet."));return}
  const groups={};for(const p of items){const g=p.group==="named"?"Named: "+p.folder:"Survey "+p.folder;(groups[g]=groups[g]||[]).push(p)}
  for(const g of Object.keys(groups)){list.append(el("div","group",g+" ("+groups[g].length+")"));const grid=el("div","grid");
   for(const p of groups[g]){const c=el("div","card");const im=el("img");im.loading="lazy";im.src="/img/"+p.path.split("/").map(encodeURIComponent).join("/")+"?t="+TOKEN;im.alt=p.pose||p.name||"picture";
    c.append(im,xbtn(async()=>{try{await api("/api/pictures/trash",{paths:[p.path]});data=data.filter(d=>d!==p);render();toast("Picture moved to the Trash",async()=>{await api("/api/pictures/restore",{paths:[p.path]})})}catch(e){toast("Failed: "+e.message)}}));
    c.append(el("div","cap",(p.name||p.pose||"")+" · "+p.time+(p.detector.length?" · sees: "+p.detector.join(", "):"")));grid.append(c)}list.append(grid)}return}
 if(tab==="trash"){const m=data.memory.map(t=>({t,txt:t.kind+": "+(t.row.fact||t.row.caption||t.row.user_text||"")})),pics=data.pictures;
  const b=el("button","btn danger","Empty trash");b.onclick=async()=>{if(Date.now()-confirmAt>4000){confirmAt=Date.now();b.textContent="Click again to delete for good";return}
   try{const r=await api("/api/empty-trash",{});toast("Deleted for good: "+r.memory.removed+" records, "+r.pictures.removed+" pictures");load()}catch(e){toast("Failed: "+e.message)}};$("#extra").append(b);
  if(!m.length&&!pics.length)list.append(el("div","empty","The trash is empty."));
  for(const {t,txt} of m){const row=el("div","row"),main=el("div","main");main.append(el("div","",txt),el("div","meta","deleted "+t.deleted_at));const r=el("button","btn","Restore");
   r.onclick=async()=>{try{await api("/api/restore",{trash_id:t.trash_id});toast("Restored");load()}catch(e){toast("Could not restore: "+e.message)}};row.append(main,r);list.append(row)}
  for(const p of pics){const row=el("div","row"),main=el("div","main");main.append(el("div","","picture "+p.path),el("div","meta",Math.round(p.bytes/1000)+" KB"));const r=el("button","btn","Restore");
   r.onclick=async()=>{try{await api("/api/pictures/restore",{paths:[p.path]});toast("Restored");load()}catch(e){toast("Could not restore: "+e.message)}};row.append(main,r);list.append(row)}return}
 const items=data.filter(r=>!f||JSON.stringify(r).toLowerCase().includes(f));if(!items.length){list.append(el("div","empty","Nothing here."));return}
 for(const r of items){const row=el("div","row"),main=el("div","main");
  if(tab==="exchanges"){main.append(el("div","",r.user_text),el("div","q",r.assistant_text),el("div","meta",r.ts+(r.actions?" · "+r.actions:"")))}
  else if(tab==="observations"){main.append(el("div","",r.caption),el("div","meta",r.ts+(r.labels?" · detector: "+r.labels:"")))}
  else{main.append(el("div","",r.fact),el("div","meta","#"+r.id+" · "+r.ts.slice(0,10)+(r.core?" · core":"")+" · importance "+r.importance))}
  row.append(main,xbtn(async()=>{try{const t=await api("/api/delete",{kind:tab,id:r.id});data=data.filter(d=>d!==r);render();toast("Moved to the Trash",async()=>{await api("/api/restore",{trash_id:t.trash_id})})}catch(e){toast("Failed: "+e.message)}}));list.append(row)}}
window.addEventListener("hashchange",()=>{const h=location.hash.replace("#","");if(TABS.some(t=>t[0]===h)){tab=h;drawTabs();load()}});
$("#q").oninput=()=>{if(tab==="facts"||tab==="exchanges"||tab==="observations"){clearTimeout(window.qt);window.qt=setTimeout(load,300)}else render()};$("#refresh").onclick=load;drawTabs();load();
</script></body></html>"""


PIDFILE = Path(os.path.expanduser("~/.g2_review.pid"))
LOG = Path(os.path.expanduser("~/g2_logs/review_server.log"))


def _ping(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1.5) as r:
            return json.loads(r.read()).get("app") == "g2review"
    except Exception:  # noqa: BLE001
        return False


def serve(port: int) -> int:
    pi = os.environ.get("G2_PI")
    if not pi:
        print("set G2_PI to user@host of the Pi (in ~/.zshrc)", file=sys.stderr, flush=True)
        return 2
    token = secrets.token_urlsafe(24)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(App(Remote(pi)), token, port))
    PIDFILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=srv.shutdown, daemon=True).start())
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            PIDFILE.unlink()
        except OSError:
            pass
    return 0


def stop() -> int:
    try:
        pid = int(PIDFILE.read_text())
        os.kill(pid, signal.SIGTERM)
        print(f"review page stopped (pid {pid})", flush=True)
    except (OSError, ValueError):
        print("the review page is not running", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--tab", default="facts")
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--serve", action="store_true", help="(internal) run the server in the foreground")
    ap.add_argument("--stop", action="store_true")
    a = ap.parse_args(argv)
    if a.stop:
        return stop()
    if a.serve:
        return serve(a.port)
    if not os.environ.get("G2_PI"):
        print("set G2_PI to user@host of the Pi (in ~/.zshrc)", file=sys.stderr, flush=True)
        return 2
    if not _ping(a.port):                                   # first call: start the page as a background server, then wait for it
        LOG.parent.mkdir(parents=True, exist_ok=True)
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--serve", "--port", str(a.port)], stdout=open(LOG, "a"), stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        for _ in range(40):
            if _ping(a.port):
                break
            time.sleep(0.15)
        else:
            print(f"the review page did not start; see {LOG}", file=sys.stderr, flush=True)
            return 1
    url = f"http://127.0.0.1:{a.port}/#{a.tab}"
    print(f"G2 review page: {url}   (stop it with: g2pics stop)", flush=True)
    if not a.no_open and not os.environ.get("G2_REVIEW_NO_OPEN"):
        webbrowser.open(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
