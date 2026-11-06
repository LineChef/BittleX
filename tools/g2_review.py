#!/usr/bin/env python3
"""A review page for G2's memory and saved pictures, with an X on every record.

    g2pimem            # opens this page on the Facts tab (g2pimem <subcommand> still prints text: log 20, search ..., usage)
    g2pics             # opens this page on the Pictures tab (g2pics status / pull still print or copy)
    python3 tools/g2_review.py [--tab facts|exchanges|observations|pictures|looks|walls|trash] [--no-open] [--stop]

The page runs as a background server (so your terminal is free): the first call starts it, later calls just open the browser. `--stop` ends it. Log: ~/g2_logs/review_server.log.

Tabs: Facts, Conversations, Observations (what G2 noticed), Pictures (survey stops and objects you named), Looks (throwaway left / right look pictures), Walls, Trash. The X moves a record to the Trash
(you get an Undo for a few seconds, and the Trash tab restores anything later); only "Empty trash" deletes for good, and it asks twice. A safe copy of the
memory database is made before the first delete of each session. The tabs read the copy of G2's data on this Mac (the newest memory snapshot in ~/Desktop/G2Memory/memory-backups,
the pictures in ~/Desktop/G2Memory/g2_pictures), so they work with the Pi off; "Sync now" refreshes the copy. An edit is applied to the copy at once and queued for the Pi
(tools/g2_review_queue.py), which gets it when it is reachable (needs G2_PI, e.g. user@g2pi.local). The page listens on 127.0.0.1 only and every action needs a token that only the
page you opened knows. Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import re
import secrets
import shlex
import shutil
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

CACHE = Path(os.path.expanduser("~/Desktop/G2Memory/g2_pictures/explore"))
WALL_CACHE = Path(os.path.expanduser("~/Desktop/G2Memory/g2_pictures/wall"))       # the wall recognition pictures (~/g2_wall_pics on the Pi) and the ring of near-wall pictures: kept apart from the object pictures so that
                                                                  # near-duplicates are never auto-pruned and nothing here is offered for naming or the object library
KINDS = ("facts", "exchanges", "observations")


def read_people_marks() -> set:
    """Pictures marked by hand as containing a person (`people.json` in the pictures folder; the curation tool leaves them out of the object library)."""
    try:
        return set(json.loads((CACHE / "people.json").read_text()))
    except (OSError, ValueError):
        return set()


PROMOTED = Path(__file__).resolve().parents[1] / "training_data" / "exploration" / "promoted"      # labelled pictures you promoted: the training data (gitignored; never in the repo)


def read_roam_labels() -> dict:
    """Your labels on the roam wall pictures: {"ring/<file>.jpg": {"label", "distance_in", "note"}}."""
    try:
        return dict(json.loads((WALL_CACHE / "roam_labels.json").read_text()))
    except (OSError, ValueError):
        return {}


def read_rooms() -> dict:
    """Your room labels for the pictures (B11 place memory): {picture file name: room}. Kept on this Mac next to the pictures (`rooms.json`); keyed by the file name, which stays the same when a
    picture is named and moves into an object's folder."""
    try:
        return {str(k): str(v) for k, v in json.loads((CACHE / "rooms.json").read_text()).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def read_unpromoted() -> set:
    """Pictures you took back out of the training data by hand: they are not promoted again automatically."""
    try:
        return set(json.loads((CACHE / "unpromoted.json").read_text()))
    except (OSError, ValueError):
        return set()


def read_promoted() -> dict:
    """{picture path under the pictures folder: where its training copy is}: what you promoted by hand."""
    try:
        return dict(json.loads((CACHE / "promoted.json").read_text()))
    except (OSError, ValueError):
        return {}


_curation_cache: dict = {"key": None, "rows": {}}


def curation_verdicts() -> dict:
    """{picture path: {"status": kept|weak|rejected|duplicate|people, "reason": ...}} for the survey and named pictures: the AUTOMATIC filter (too dark, blown out, blurry, flat, cut off, a person in it) and
    the near-duplicate removal, from tools/curate_exploration.py, recomputed whenever the pictures change. Nothing is deleted or moved: a filtered picture is only marked, and hidden on the page by default.
    Look pictures are never curated. {} if the curation tool's libraries (Pillow, numpy) are not installed."""
    try:
        files = sorted((f, f.stat().st_mtime) for top in ("survey", "named") for f in (CACHE / top).rglob("*") if f.suffix in (".jpg", ".json"))      # a tag removed in the page changes a sidecar
    except OSError:
        return {}
    marks = read_people_marks()
    key = (len(files), max((m for _, m in files), default=0), len(marks))
    if _curation_cache["key"] == key:
        return _curation_cache["rows"]
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import curate_exploration
        manifest = curate_exploration.curate(str(CACHE), "", None, write=False)
    except Exception:  # noqa: BLE001 -- the page works without the verdicts
        return {}
    rows = {r["file"]: {"status": r["status"], "reason": r["reason"], "duplicate_of": r.get("duplicate_of")} for r in manifest["pictures"]}
    _curation_cache.update(key=key, rows=rows)
    return rows


def picture_is_cut_off(path) -> bool | None:
    """True when a saved JPEG ends without its end marker (the camera module cut the picture short; the rest shows as flat gray); None if the file is not here yet."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return data.rstrip(b"\x00")[-2:] != b"\xff\xd9"


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


    def sync_walls(self) -> str:
        WALL_CACHE.mkdir(parents=True, exist_ok=True)
        (WALL_CACHE / "ring").mkdir(exist_ok=True)
        msgs = []
        for src, dst in (("g2_wall_pics/", str(WALL_CACHE) + "/"), (".local/share/g2/wall_pics/", str(WALL_CACHE / "ring") + "/")):
            r = subprocess.run(["rsync", "-a", f"{self.pi}:{src}", dst], capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                msgs.append((r.stderr.strip().splitlines() or ["none yet"])[-1])
        r = subprocess.run(["rsync", "-a", f"{self.pi}:.local/share/g2/wall_dryrun.jsonl", str(WALL_CACHE / "wall_dryrun.jsonl")], capture_output=True, text=True, timeout=120)     # what the estimator said at each look, to judge the roam pictures against
        return "ok" if not msgs else "; ".join(msgs)


ROOT = Path(__file__).resolve().parents[1]


class MirrorRemote(Remote):
    """The tabs read the copy of G2's data on this Mac, so they work with the Pi off (user, 2026-11-04). Memory comes from the newest valid snapshot in ~/Desktop/G2Memory/memory-backups, the
    pictures from ~/Desktop/G2Memory/g2_pictures. An edit is applied to that copy at once and also queued (tools/g2_review_queue.py) for the Pi, which gets the same command when it is reachable.
    Anything that is not data (the mic switch, the training gallery) still goes to the Pi live."""

    mirror = True

    def __init__(self, pi: str, runner=None, root: str | None = None, pictures_root=None):
        super().__init__(pi, runner)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import g2_review_queue
        self.q = g2_review_queue
        self.root = Path(root) if root else Path(g2_review_queue.folder())
        self.pictures_root = Path(pictures_root) if pictures_root else CACHE
        self.lock = threading.RLock()

    # ---- the memory copy: the newest good snapshot, plus the edits still waiting for the Pi
    def snapshot(self) -> Path | None:
        import sqlite3
        for f in sorted((self.root / "memory-backups").glob("g2_memory-*.db"), reverse=True):
            try:
                if f.stat().st_size == 0:
                    continue
                c = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
                try:
                    c.execute("SELECT COUNT(*) FROM facts").fetchone()
                finally:
                    c.close()
                return f
            except (OSError, sqlite3.Error):
                continue
        return None

    def view_paths(self) -> tuple[Path, Path]:
        return self.root / "memory" / "review_view.db", self.root / "memory" / "review_view.json"

    def copy_info(self) -> dict:
        snap = self.snapshot()
        m = re.match(r"g2_memory-(\d{8})-(\d{6})\.db", snap.name) if snap else None
        when = time.strftime("%b %-d, %-I:%M %p", time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")) if m else None
        return {"memory_from": when, "has_memory": snap is not None}

    def view(self) -> str:
        """The path of the memory copy the tabs show; rebuilt from the snapshot (and the waiting edits) when a newer snapshot arrived."""
        import shutil
        import sqlite3
        with self.lock:
            snap = self.snapshot()
            if snap is None:
                raise RuntimeError("no memory copy on this Mac yet: press Sync now while the Pi is on")
            db, key_file = self.view_paths()
            ident = {"snapshot": snap.name, "size": snap.stat().st_size}
            try:
                key = json.loads(key_file.read_text())
            except (OSError, ValueError):
                key = {}
            if db.exists() and all(key.get(k) == v for k, v in ident.items()):
                return str(db)
            db.parent.mkdir(parents=True, exist_ok=True)
            tmp = db.with_suffix(".tmp")
            shutil.copyfile(snap, tmp)
            os.replace(tmp, db)
            c = sqlite3.connect(db)
            try:
                tables = {"facts": "facts", "observations": "observations", "exchanges": "exchanges"}
                ident["max"] = {k: int(c.execute(f"SELECT COALESCE(MAX(id),0) FROM {t}").fetchone()[0]) for k, t in tables.items()}
            finally:
                c.close()
            key_file.write_text(json.dumps(ident))
            for e in self.q.pending(str(self.root)):                         # the edits not yet at the Pi go back on top of the fresh copy
                if e["module"] == "pi_pipeline.memory.review":
                    try:
                        self._run(e["module"], ["--db", str(db), *e["args"]])
                    except Exception:  # noqa: BLE001  (an edit that no longer fits stays queued; the Pi will say why)
                        pass
            return str(db)

    def rebuild(self) -> None:
        with self.lock:
            db, key = self.view_paths()
            for f in (key,):
                try:
                    f.unlink()
                except OSError:
                    pass
            self.view()

    def snap_max(self, kind: str) -> int:
        self.view()
        return int(json.loads(self.view_paths()[1].read_text()).get("max", {}).get(kind, 0))

    # ---- running the Pi's own modules on the copy
    def _run(self, module: str, argv: list[str]):
        mod = importlib.import_module(module)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                mod.main(argv)
        except SystemExit as e:
            if e.code not in (0, None):
                raise ValueError("that command was refused") from None
        lines = buf.getvalue().strip().splitlines()
        if not lines:
            raise RuntimeError("the local copy returned nothing")
        data = json.loads(lines[-1])
        if isinstance(data, dict) and "error" in data:
            raise ValueError(data["error"])
        return data

    def call(self, args: list[str]):
        module, rest = args[0], list(args[1:])
        with self.lock:
            if module == "pi_pipeline.memory.review":
                return self._memory(rest)
            if module == "pi_pipeline.vision.exploration_pictures":
                return self._pictures(rest)
            if module == "pi_pipeline.vision.wall_pictures" and rest and rest[0] in ("trash", "restore", "empty-trash"):
                return self._walls(rest)
        return super().call(args)

    def _queue(self, module: str, args: list[str], text: str, **extra):
        return self.q.add(module, args, text, str(self.root), **extra)

    def _memory(self, rest: list[str]):
        mod, sub = "pi_pipeline.memory.review", rest[0]
        db = self.view()
        if sub in ("list", "count", "trash"):
            return self._run(mod, ["--db", db, *rest])
        if sub == "backup":
            return {"backup": "the copy on this Mac"}                         # the snapshot is the safe copy
        kind_of = {"add-fact": "facts", "edit-fact": "facts", "add-observation": "observations", "edit-observation": "observations"}
        if sub in ("add-fact", "add-observation"):
            res = self._run(mod, ["--db", db, *rest])
            self._queue(mod, rest, ("Add fact: " if sub == "add-fact" else "Add observation: ") + rest[1][:80], local_id=res["id"], local_kind=kind_of[sub])
            return res
        if sub in ("edit-fact", "edit-observation"):
            rid, kind = int(rest[1]), kind_of[sub]
            res = self._run(mod, ["--db", db, *rest])
            if rid > self.snap_max(kind):                                    # a row the Pi does not have yet: change the waiting "add" instead
                for e in self.q.pending(str(self.root)):
                    if e.get("local_id") == rid and e.get("local_kind") == kind:
                        flags = {rest[i]: rest[i + 1] for i in range(2, len(rest) - 1, 2)}
                        a = list(e["args"])
                        if sub == "edit-fact":
                            fact = flags.get("--fact", a[1])
                            imp = flags.get("--importance", a[a.index("--importance") + 1] if "--importance" in a else "3")
                            core = flags.get("--core", "1" if "--core" in a else "0") == "1"
                            a = ["add-fact", fact, "--importance", imp] + (["--core"] if core else [])
                        else:
                            cap = flags.get("--caption", a[1])
                            lab = flags.get("--labels", a[a.index("--labels") + 1] if "--labels" in a else "")
                            a = ["add-observation", cap, "--labels", lab]
                        rows = self.q.pending(str(self.root))
                        for r in rows:
                            if r["id"] == e["id"]:
                                r["args"], r["text"] = a, ("Add fact: " if sub == "edit-fact" else "Add observation: ") + a[1][:80]
                        self.q.save(rows, str(self.root))
                return res
            self._queue(mod, rest, f"Change {'fact' if sub == 'edit-fact' else 'observation'} #{rid}" + (f": {rest[rest.index('--fact') + 1][:70]}" if "--fact" in rest else ""))
            return res
        if sub == "delete":
            kind, rid = rest[1], int(rest[2])
            res = self._run(mod, ["--db", db, *rest])
            if rid > self.snap_max(kind):                                    # never reached the Pi: just drop its waiting "add"
                for e in self.q.pending(str(self.root)):
                    if e.get("local_id") == rid and e.get("local_kind") == kind:
                        self.q.remove(e["id"], str(self.root))
                return res
            self._queue(mod, rest, f"Delete {kind[:-1] if kind.endswith('s') else kind} #{rid}")
            return res
        if sub == "restore":
            tid = int(rest[1])
            row = next((t for t in self._run(mod, ["--db", db, "trash"]) if t["trash_id"] == tid), None)
            res = self._run(mod, ["--db", db, *rest])
            if row is None:
                return res
            kind, rid = row["kind"], int(row["row_id"])
            waiting = next((e for e in self.q.pending(str(self.root)) if e["module"] == mod and e["args"][:3] == ["delete", kind, str(rid)]), None)
            if waiting:                                                      # its delete never left this Mac: cancel it
                self.q.remove(waiting["id"], str(self.root))
            elif rid > self.snap_max(kind):                                  # a row added here, deleted, now back: queue its "add" again
                r = row["row"]
                if kind == "facts":
                    self._queue(mod, ["add-fact", r["fact"], "--importance", str(r.get("importance", 3))] + (["--core"] if r.get("core") else []), "Add fact: " + r["fact"][:80], local_id=rid, local_kind=kind)
                elif kind == "observations":
                    self._queue(mod, ["add-observation", r["caption"], "--labels", r.get("labels") or ""], "Add observation: " + r["caption"][:80], local_id=rid, local_kind=kind)
            else:
                self._queue(mod, rest, f"Put record #{rid} back")
            return res
        if sub == "empty-trash":
            res = self._run(mod, ["--db", db, *rest])
            self._queue(mod, rest, "Empty the memory Trash for good")
            return res
        raise ValueError(f"not available on the copy: {sub}")

    def _pictures(self, rest: list[str]):
        mod, sub = "pi_pipeline.vision.exploration_pictures", rest[0]
        argv = ["--root", str(self.pictures_root), *rest]
        if sub in ("list", "trash-list", "status"):
            return self._run(mod, argv)
        n = max(len(rest) - 1, 1)
        if sub == "restore":
            waiting = next((e for e in self.q.pending(str(self.root)) if e["module"] == mod and e["args"] == ["trash", *rest[1:]]), None)
            res = self._run(mod, argv)
            if waiting:
                self.q.remove(waiting["id"], str(self.root))
            else:
                self._queue(mod, rest, f"Put {n} picture(s) back")
            return res
        res = self._run(mod, argv)
        text = {"trash": f"Move {n} picture(s) to the Trash", "name": f"Name {n - 1} picture(s) {rest[1]}", "label": f"Flag a label on {rest[1]}", "move": f"Move {n} picture(s)",
                "empty-trash": "Empty the picture Trash for good"}.get(sub, sub)
        self._queue(mod, rest, text)
        return res

    def _walls(self, rest: list[str]):
        mod, sub = "pi_pipeline.vision.wall_pictures", rest[0]
        names = rest[1:]
        if sub == "restore":
            waiting = next((e for e in self.q.pending(str(self.root)) if e["module"] == mod and e["args"] == ["trash", *names]), None)
            if waiting:
                self.q.remove(waiting["id"], str(self.root))
            else:
                self._queue(mod, rest, f"Put {len(names)} wall picture(s) back")
            return {"restored": names}
        self._queue(mod, rest, f"Move {len(names)} wall picture(s) to the Trash" if sub == "trash" else "Empty the wall-picture Trash for good")
        return {"moved": names} if sub == "trash" else {"removed": 0}


def read_estimates() -> dict:
    """{roam picture file name: what the wall estimator read at that look} from `wall_dryrun.jsonl` (the lines that name a kept picture)."""
    out = {}
    try:
        for line in (WALL_CACHE / "wall_dryrun.jsonl").read_text().splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("pic"):
                out[d["pic"]] = {"state": d.get("state"), "nearest_in": d.get("nearest_in"), "group_in": d.get("group_in"), "turn": d.get("turn")}
    except OSError:
        pass
    return out


class App:
    """The actions behind the page. Pure of HTTP, so it can be tested with a fake Remote."""

    def __init__(self, remote: Remote):
        self.remote = remote
        self._sync: subprocess.Popen | None = None
        self._backed_up = False

    @property
    def mirror(self) -> bool:
        return bool(getattr(self.remote, "mirror", False))

    def facts_info(self) -> dict:
        """The memory limits the Facts tab shows next to its counts: how many core facts G2 is given, and how many facts the memory keeps."""
        try:
            sys.path.insert(0, str(ROOT))
            from pi_pipeline.config import settings
            return {"core_max": int(settings.memory_core_max), "max_facts": int(settings.memory_max_facts)}
        except Exception:  # noqa: BLE001
            return {"core_max": 12, "max_facts": 30}

    def facts_tidy(self) -> dict:
        """What the Facts tab's tidy-up view lists, found with the memory's own rules (pi_pipeline/memory/store.py): pairs of facts that say nearly the same thing, facts that name a date or
        time (the memory refuses those when G2 saves them himself), and more than one "I look like ..." fact (that is a single slot)."""
        sys.path.insert(0, str(ROOT))
        from pi_pipeline.memory.store import NEAR_DUPLICATE, has_temporal_detail, similarity
        rows = self.remote.memory("list", "facts", "--limit", "2000", "--query", "")
        keep = ("id", "fact", "source", "importance", "core", "ts", "injected", "declared", "matched", "last_used")
        slim = [{k: r.get(k) for k in keep} for r in rows]
        pairs = []
        for i, a in enumerate(slim):
            for b in slim[i + 1:]:
                sc = similarity(a["fact"], b["fact"])
                if sc >= NEAR_DUPLICATE:                                   # the memory's own rule for "the same fact reworded" (a cat and a dog with the same name stay two facts)
                    pairs.append({"a": a, "b": b, "score": round(sc, 2)})
        pairs.sort(key=lambda p: -p["score"])
        looks = [r for r in slim if re.match(r"\s*i look like\b", r["fact"] or "", re.I)]
        return {"duplicates": pairs[:40], "dated": [r for r in slim if has_temporal_detail(r["fact"] or "")], "look_like": looks if len(looks) > 1 else []}

    def review_state(self) -> dict:
        """What the tabs are showing and what still waits for the Pi (the queue of tools/g2_review_queue.py)."""
        if not self.mirror:
            return {"mirror": False, "pending": [], "history": [], "copy": {}}
        q = self.remote.q
        rows = q.pending(str(self.remote.root))
        def undo_ok(e):
            a0 = e["args"][0]
            return (e["module"].endswith("memory.review") and a0 != "empty-trash") or (e["module"].endswith("exploration_pictures") and a0 in ("trash", "restore")) or (e["module"].endswith("wall_pictures") and a0 == "trash")
        return {"mirror": True, "copy": self.remote.copy_info(), "history": q.history(str(self.remote.root), 10),
                "pending": [{"id": e["id"], "text": q.describe(e), "error": e.get("error"), "cancellable": bool(undo_ok(e))} for e in rows]}

    def review_cancel(self, edit_id: str) -> dict:
        """Take one waiting edit back: its effect on the copy is undone too (not possible for naming, moving and flagging pictures, which are sent on the next sync)."""
        r = self.remote
        with r.lock:
            e = next((x for x in r.q.pending(str(r.root)) if x["id"] == edit_id), None)
            if e is None:
                raise ValueError("that edit has already gone")
            mod, a = e["module"], e["args"]
            if mod.endswith("memory.review") and a[0] != "empty-trash":
                r.q.remove(edit_id, str(r.root))
                r.rebuild()
            elif mod.endswith("exploration_pictures") and a[0] in ("trash", "restore"):
                r._run(mod, ["--root", str(r.pictures_root), "restore" if a[0] == "trash" else "trash", *a[1:]])
                r.q.remove(edit_id, str(r.root))
            elif mod.endswith("wall_pictures") and a[0] == "trash":
                self._wall_back(a[1:])
                r.q.remove(edit_id, str(r.root))
            else:
                raise ValueError("this one cannot be taken back from here; it is sent to the Pi on the next sync")
        return self.review_state()

    def review_apply(self) -> dict:
        res = self.remote.q.apply(str(self.remote.root), self.remote.pi)
        if res["applied"]:
            self.remote.rebuild()
        return {**res, **self.review_state()}

    def _wall_back(self, names: list[str]) -> None:
        trash = WALL_CACHE.parent / "wall_trash"
        for n in names:
            for ext in (".jpg", ".json"):
                src = trash / (n + ext)
                if src.exists():
                    dst = WALL_CACHE / (n + ext)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))

    @staticmethod
    def sync_last() -> dict | None:
        """What the latest sync run did, from ~/Desktop/G2Memory/sync_last.json (tools/g2_sync.sh): {"outcome": ok|partial|offline|busy|running|no_pi, "message", "when" (12-hour)}."""
        try:
            d = json.loads(Path(os.path.expanduser("~/Desktop/G2Memory/sync_last.json")).read_text())
            d["when"] = time.strftime("%b %-d, %-I:%M %p", time.strptime(d["time"], "%Y-%m-%d %H:%M:%S"))
            return d
        except (OSError, ValueError, KeyError):
            return None

    def sync_now(self, start: bool = True) -> dict:
        """The "Sync now" button (user, 2026-11-01): every copy from the Pi now (tools/g2_sync.sh run --force all), in the background. Returns whether one is running and what the last run did
        (the script exits 0 even when the Pi does not answer, so the exit code alone cannot say whether anything was copied)."""
        if self._sync is not None and self._sync.poll() is None:
            return {"running": True, "started": False, "last": self.sync_last()}
        if not start:
            return {"running": False, "started": False, "result": None if self._sync is None else self._sync.returncode, "last": self.sync_last()}
        LOG_DIR = Path(os.path.expanduser("~/g2_logs"))
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        script = Path(__file__).resolve().parent / "g2_sync.sh"
        self._sync = subprocess.Popen(["bash", str(script), "run", "--force", "all"], env={**os.environ, "G2_PI": self.remote.pi},
                                      stdout=open(LOG_DIR / "sync_button.log", "a"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        return {"running": True, "started": True, "last": self.sync_last()}

    def mic(self, turn_on: bool = False) -> dict:
        """G2's wake word: {"paused", "minutes_left", "until"}; `turn_on` ends a "mic off" pause early (voice/wake_pause.py)."""
        return self.remote.call(["pi_pipeline.voice.wake_pause", "on" if turn_on else "status", "--json"])

    def sync_status(self) -> list:
        """When each copy from the Pi last worked, for the line under the title (tools/g2_sync.sh status)."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import g2_goals_view
        return g2_goals_view.sync_status(os.path.expanduser("~/Desktop/G2Memory/sync_status.json"))

    def walls(self) -> list:
        """The wall pictures in the local cache: the recognition shots (with their labels, distance in inches, flags and what the estimator read) and the ring of pictures G2 kept
        in a roam when a wall was near or blocked (named after the look: wall_<date>_<time>_<state>.jpg)."""
        out = []
        try:
            labels = json.loads((WALL_CACHE / "labels.json").read_text())
        except (OSError, ValueError):
            labels = {}
        for f in sorted(WALL_CACHE.glob("shot_*.jpg")):
            info = labels.get(f.stem, {})
            out.append({"file": f.name, "path": f.name, "src": "recognition", "label": info.get("label", "unlabelled"), "distance_in": info.get("distance_in"),
                        "angle_deg": info.get("angle_deg"), "set": info.get("set"), "flags": info.get("flags", []), "note": info.get("note", ""), "base_rows": info.get("base_rows"),
                        "expected_turn": info.get("expected_turn")})
        mine, est = read_roam_labels(), read_estimates()
        for f in sorted((WALL_CACHE / "ring").glob("wall_*.jpg"), reverse=True):
            state = f.stem.rsplit("_", 1)[-1]
            m = mine.get("ring/" + f.name, {})
            out.append({"file": f.name, "path": "ring/" + f.name, "src": "roam", "label": m.get("label") or "roam: " + state, "labelled": bool(m.get("label")), "state": state,
                        "distance_in": m.get("distance_in"), "note": m.get("note") or f.stem[5:], "flags": [],
                        "estimate": est.get(f.name)})
        return out

    def label_wall(self, path: str, label: str, distance_in=None, note: str = ""):
        """Label a roam picture by hand: what it shows (wall, door, corner, chair, ...), optionally the real distance in inches and a note. Kept on this Mac next to the pictures (`roam_labels.json`); an empty label clears it."""
        name = self._wall_name(path)
        if not name.startswith("ring/"):
            raise ValueError("only roam pictures are labelled here (recognition shots carry their labels from the Pi)")
        label = " ".join(str(label or "").split())[:40]
        marks = read_roam_labels()
        if not label:
            marks.pop(name, None)
        else:
            d = None
            if distance_in not in (None, ""):
                d = float(distance_in)
                if not 0 < d < 600:
                    raise ValueError("distance in inches, for example 16")
            marks[name] = {"label": label, "distance_in": d, "note": " ".join(str(note or "").split())[:120]}
        WALL_CACHE.mkdir(parents=True, exist_ok=True)
        (WALL_CACHE / "roam_labels.json").write_text(json.dumps(marks, indent=1))
        return {"labelled": name, "label": label}

    @staticmethod
    def _wall_name(p: str) -> str:
        if not re.fullmatch(r"(ring/wall_[A-Za-z0-9_\-]+|shot_\d+)\.jpg", p or ""):
            raise ValueError(f"not a wall picture path: {p!r}")
        return p[:-4] if p.startswith("shot_") else p

    def trash_walls(self, paths: list[str]):
        """Move wall pictures to a trash folder on the Pi (nothing is erased; the page's Undo restores them) and drop the local copies; the next sync brings back anything restored."""
        names = [self._wall_name(p) for p in paths]
        out = self.remote.call(["pi_pipeline.vision.wall_pictures", "trash", *names])
        trash = WALL_CACHE.parent / "wall_trash"
        for p in paths:
            for f in (WALL_CACHE / p, (WALL_CACHE / p).with_suffix(".json")):
                try:
                    if self.mirror and f.exists():                        # kept on this Mac so Undo can bring it back before the Pi has been told
                        dst = trash / f.relative_to(WALL_CACHE)
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(f), str(dst))
                    else:
                        f.unlink()
                except OSError:
                    pass
        return out

    def restore_walls(self, paths: list[str]):
        names = [self._wall_name(p) for p in paths]
        out = self.remote.call(["pi_pipeline.vision.wall_pictures", "restore", *names])
        if self.mirror:
            self._wall_back(names)
        else:
            self.remote.sync_walls()
        return out

    def list(self, kind: str, q: str = "", limit: int = 300):
        if kind not in KINDS:
            raise ValueError("unknown kind")
        return self.remote.memory("list", kind, "--limit", str(int(limit)), "--query", q)

    def goals(self) -> dict:
        """The Goals tab: what G2 learned for each goal, from the copy of the goal data on this Mac (works with the Pi off)."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import g2_goals_view
        return g2_goals_view.build()

    def goal_edit(self, op: dict) -> dict:
        """Queue one Goals-tab edit on this Mac (applied to the Pi later: tools/g2_goal_edits.py). A bad edit is refused here, with the reason."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import g2_goal_edits
        row = g2_goal_edits.add(op)
        return {"ok": True, "id": row["id"], "pending": g2_goal_edits.with_text(g2_goal_edits.pending())}

    def goal_edit_cancel(self, edit_id: str) -> dict:
        import g2_goal_edits
        return {"ok": g2_goal_edits.cancel(edit_id), "pending": g2_goal_edits.with_text(g2_goal_edits.pending())}

    def goal_edits_apply(self) -> dict:
        """Send the queued edits to the Pi now (only when it is up and no goal session runs), then copy the goal data down again."""
        import g2_goal_edits
        res = g2_goal_edits.apply()
        if res["applied"]:
            try:
                subprocess.run(["bash", str(Path(__file__).resolve().parent / "g2_goal_pull.sh")], capture_output=True, timeout=150)
            except (OSError, subprocess.TimeoutExpired):
                pass
        res["pending"] = g2_goal_edits.with_text(g2_goal_edits.pending())
        return res

    def counts(self) -> dict:
        """Totals for the tab labels: records of each memory kind, pictures kept, and what is in the Trash."""
        out = dict(self.remote.memory("count"))
        pics = self.remote.pictures("list")
        out["pictures"] = sum(1 for p in pics if p.get("group") != "looks")             # the throwaway look pictures have their own tab
        out["looks"] = sum(1 for p in pics if p.get("group") == "looks")
        t = self.trash()
        out["trash"] = len(t["memory"]) + len(t["pictures"])
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import g2_goal_edits
        out["sync"] = (len(self.remote.q.pending(str(self.remote.root))) if self.mirror else 0) + len(g2_goal_edits.pending())          # the Waiting to sync tab
        return out

    def waiting(self) -> dict:
        """The Waiting to sync tab: every edit queued on this Mac for the Pi (memory, pictures and goals) and the last ones sent."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import g2_goal_edits
        hist = g2_goal_edits.history()[:5] if hasattr(g2_goal_edits, "history") else []
        return {"goals": g2_goal_edits.with_text(g2_goal_edits.pending()), "goal_history": hist}

    def delete(self, kind: str, row_id: int):
        if kind not in KINDS:
            raise ValueError("unknown kind")
        if not self._backed_up:                              # one safe copy of the database before this session's first delete
            self.remote.memory("backup")
            self._backed_up = True
        return self.remote.memory("delete", kind, str(int(row_id)))

    def _backup_once(self):
        if not self._backed_up:                              # one safe copy of the database before this session's first change
            self.remote.memory("backup")
            self._backed_up = True

    def add_fact(self, fact: str, importance: int = 3, core: bool = False):
        self._backup_once()
        args = ["add-fact", str(fact), "--importance", str(int(importance))] + (["--core"] if core else [])
        return self.remote.memory(*args)

    def edit_fact(self, fact_id: int, fact=None, importance=None, core=None, ts=None):
        self._backup_once()
        args = ["edit-fact", str(int(fact_id))]
        if fact is not None:
            args += ["--fact", str(fact)]
        if importance is not None:
            args += ["--importance", str(int(importance))]
        if core is not None:
            args += ["--core", "1" if core else "0"]
        if ts is not None:
            args += ["--ts", str(ts)]
        return self.remote.memory(*args)

    def add_observation(self, caption: str, labels: str = ""):
        self._backup_once()
        return self.remote.memory("add-observation", str(caption), "--labels", str(labels or ""))

    def edit_observation(self, obs_id: int, caption=None, labels=None):
        self._backup_once()
        args = ["edit-observation", str(int(obs_id))]
        if caption is not None:
            args += ["--caption", str(caption)]
        if labels is not None:
            args += ["--labels", str(labels)]
        return self.remote.memory(*args)

    def restore(self, trash_id: int):
        return self.remote.memory("restore", str(int(trash_id)))

    def pictures(self):
        items = self.remote.pictures("list")
        marks = read_people_marks()
        verdicts, promoted = curation_verdicts(), read_promoted()
        self._auto_promote(items, verdicts, promoted, marks)
        promoted, rooms = read_promoted(), read_rooms()
        for p in items:
            p["room"] = rooms.get(p["path"].rsplit("/", 1)[-1], "") if p.get("group") != "looks" else ""
            p["cut_off"] = picture_is_cut_off(CACHE / p["path"])
            p["person"] = p["path"] in marks
            v = verdicts.get(p["path"])
            p["status"] = v["status"] if v else ("look" if p.get("group") == "looks" else "unknown")
            p["reason"] = v["reason"] if v else ""
            p["promoted"] = p["path"] in promoted
        return items

    def _auto_promote(self, items, verdicts, promoted, marks) -> None:
        """A labelled picture is assumed ready for training (user, 2026-10-10): every picture in a name's folder that the filter kept (not rejected, not a duplicate, no person in it) and that you have not
        taken out by hand is promoted automatically, which also queues it for the robot's gallery. Never raises."""
        skip = read_unpromoted()
        for p in items:
            rel = p["path"]
            v = verdicts.get(rel) or {}
            if p.get("group") != "named" or rel in promoted or rel in skip or rel in marks or v.get("status") not in ("kept", "weak"):
                continue
            try:
                self.promote_pictures([rel])
            except Exception:  # noqa: BLE001 -- a picture that cannot be promoted now is tried again on the next load
                continue

    def promote_pictures(self, paths: list[str], value: bool = True):
        """Promote labelled pictures into the training data (`training_data/exploration/promoted/<name>/`), or take them back out. Only a picture you labelled (it is in a name's folder), that the filter
        kept (not rejected, not a duplicate, no person in it) can be promoted. The original stays where it is."""
        rels = [self._rel(p) for p in paths]
        promoted = read_promoted()
        skip = read_unpromoted()
        verdicts, marks = curation_verdicts(), read_people_marks()
        done = []
        for rel in rels:
            if not value:
                dest = promoted.pop(rel, None)
                for f in ([PROMOTED.parent.parent / dest, (PROMOTED.parent.parent / dest).with_suffix(".json")] if dest else []):
                    try:
                        f.unlink()
                    except OSError:
                        pass
                done.append(rel)
                skip.add(rel)                                   # taken out by hand: not promoted again automatically
                continue
            skip.discard(rel)
            if not rel.startswith("named/"):
                raise ValueError("label it first (Name), then promote")
            v = verdicts.get(rel) or {}
            if rel in marks or v.get("status") in ("people", "rejected", "duplicate"):
                raise ValueError(f"not promoted: {v.get('status') or 'a person is in it'} ({v.get('reason') or 'flagged'})")
            src = CACHE / rel
            if not src.exists():
                raise ValueError("that picture is not here yet (refresh)")
            name = rel.split("/")[1]
            dst = PROMOTED / name / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if src.with_suffix(".json").exists():
                shutil.copy2(src.with_suffix(".json"), dst.with_suffix(".json"))
            promoted[rel] = str(dst.relative_to(PROMOTED.parent.parent))
            done.append(rel)
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "promoted.json").write_text(json.dumps(promoted, indent=1))
        (CACHE / "unpromoted.json").write_text(json.dumps(sorted(skip)))
        out = {"promoted" if value else "unpromoted": done}
        if value and done:                                     # loading into the robot's gallery is automatic: the Pi learns the picture under its label (now, or at the next exploration start)
            try:
                out["gallery"] = self.remote.call(["pi_pipeline.vision.promoted_loader", "add", *done])
            except Exception as e:  # noqa: BLE001 -- the training copy is made either way
                out["gallery"] = {"error": str(e)[:120]}
        return out

    def mark_people(self, paths: list[str], value: bool):
        """Flag (or unflag) pictures as containing a person. Kept on this Mac only, next to the pictures; nothing is deleted."""
        rels = [self._rel(p) for p in paths]
        marks = read_people_marks()
        marks = (marks | set(rels)) if value else (marks - set(rels))
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "people.json").write_text(json.dumps(sorted(marks), indent=1))
        return {"marked": rels if value else [], "unmarked": [] if value else rels}

    def set_rooms(self, rooms: dict):
        """Set the room of pictures by hand ({picture path: room}; an empty room clears it). Survey and named pictures only: the look pictures are throwaways. Returns the rooms they had, for the Undo."""
        new = {}
        for p, room in dict(rooms).items():
            rel = self._rel(p)
            if rel.startswith("looks/"):
                raise ValueError("look pictures do not get a room")
            new[rel.rsplit("/", 1)[-1]] = " ".join(str(room or "").lower().split())[:40]
        if not new:
            raise ValueError("no pictures")
        marks = read_rooms()
        previous = {}
        for p in rooms:
            previous[p] = marks.get(p.rsplit("/", 1)[-1], "")
        for f, room in new.items():
            if room:
                marks[f] = room
            else:
                marks.pop(f, None)
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "rooms.json").write_text(json.dumps(dict(sorted(marks.items())), indent=1))
        return {"set": len(new), "previous": previous}

    def name_pictures(self, paths: list[str], name: str):
        """Name pictures by hand: they move to named/<name>/ on the Pi (and here), where a voice naming would have put them. Returns the moves, for the Undo."""
        rels = [self._rel(p) for p in paths]
        nm = " ".join(str(name or "").split())
        if not nm:
            raise ValueError("give a name")
        out = self.remote.pictures("name", nm, *rels)
        for m in ([] if self.mirror else out.get("named", [])):                        # the old local copy goes; the new one comes with the sync
            f = CACHE / m["from"]
            if m["from"] != m["to"]:
                for g in (f, f.with_suffix(".json")):
                    try:
                        g.unlink()
                    except OSError:
                        pass
        if not self.mirror:
            self.remote.sync_pictures()
        return out

    def dismiss_label(self, path: str, label: str, restore: bool = False):
        """Flag a detector label on a picture as wrong (or put it back); the Pi's sidecar keeps the record, the page stops showing it."""
        label = str(label or "").strip()
        if not label or len(label) > 60:
            raise ValueError("no label")
        return self.remote.pictures("label", self._rel(path), label, *(["--restore"] if restore else []))

    def move_pictures(self, pairs: list[list[str]]):
        out = self.remote.pictures("move", *[f"{self._rel(a)}:{self._rel(b)}" for a, b in pairs])
        for a, b in pairs:
            for g in ([] if self.mirror else (CACHE / b, (CACHE / b).with_suffix(".json"))):
                try:
                    g.unlink()
                except OSError:
                    pass
        if not self.mirror:
            self.remote.sync_pictures()
        return out

    def trash_pictures(self, paths: list[str]):
        out = self.remote.pictures("trash", *[self._rel(p) for p in paths])
        for p in ([] if self.mirror else paths):               # the local copy goes too (on the mirror the local module already moved it to the Trash)
            f = CACHE / self._rel(p)
            for g in (f, f.with_suffix(".json")):
                try:
                    g.unlink()
                except OSError:
                    pass
        return out

    def restore_pictures(self, paths: list[str]):
        out = self.remote.pictures("restore", *[self._rel(p) for p in paths])
        if not self.mirror:
            self.remote.sync_pictures()
        return out

    def trash(self):
        return {"memory": self.remote.memory("trash"), "pictures": self.remote.pictures("trash-list")}

    def empty_trash(self):
        out = {"memory": self.remote.memory("empty-trash"), "pictures": self.remote.pictures("empty-trash")}
        try:
            out["walls"] = self.remote.call(["pi_pipeline.vision.wall_pictures", "empty-trash"])
        except Exception:  # noqa: BLE001 -- an older Pi without the command: the rest was emptied
            out["walls"] = {"removed": 0}
        return out

    @staticmethod
    def _rel(p: str) -> str:
        if not re.fullmatch(r"(survey|named|looks)/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-.]+\.jpg", p or ""):
            raise ValueError(f"not a picture path: {p!r}")
        return p


class Presence:
    """Which browser tabs have the page open (user, 2026-11-01: closing the g2pics tab ends the server). Each tab sends a beat every few seconds and a bye when it closes; the server
    stops when no tab is left for GRACE_S (a reload says bye then beats again at once, so it survives), a tab silent for EXPIRE_S counts as closed (a hidden tab's timers are slowed by
    the browser), and a server nobody ever opened stops after START_S."""
    GRACE_S = 6.0
    EXPIRE_S = 600.0
    START_S = 90.0

    def __init__(self, clock=time.time):
        self.clock = clock
        self.tabs: dict[str, float] = {}
        self.born = clock()
        self.seen_any = False
        self.empty_since: float | None = None
        self._lock = threading.Lock()

    def beat(self, tab: str) -> None:
        with self._lock:
            self.tabs[tab] = self.clock()
            self.seen_any = True
            self.empty_since = None

    def bye(self, tab: str) -> None:
        with self._lock:
            self.tabs.pop(tab, None)
            if not self.tabs and self.empty_since is None:
                self.empty_since = self.clock()

    def due(self) -> bool:
        """True when the server should stop now."""
        with self._lock:
            now = self.clock()
            for t in [t for t, at in self.tabs.items() if now - at > self.EXPIRE_S]:
                del self.tabs[t]
                if not self.tabs and self.empty_since is None:
                    self.empty_since = now
            if self.tabs:
                return False
            if not self.seen_any:
                return now - self.born >= self.START_S
            return self.empty_since is not None and now - self.empty_since >= self.GRACE_S


def make_handler(app: App, token: str, port: int, presence: Presence | None = None):
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
                if u.path == "/api/sync":
                    return self._json({"tasks": app.sync_status(), **app.sync_now(start=False)})
                if u.path == "/api/goals":
                    return self._json(app.goals())
                if u.path == "/api/facts/tidy":
                    return self._json(app.facts_tidy())
                if u.path == "/api/facts/info":
                    return self._json(app.facts_info())
                if u.path == "/api/waiting":
                    return self._json(app.waiting())
                if u.path == "/api/review/state":
                    return self._json(app.review_state())
                if u.path == "/api/counts":
                    return self._json(app.counts())
                if u.path == "/api/pictures":
                    return self._json(app.pictures())
                if u.path.startswith("/wimg/"):
                    rel = urllib.parse.unquote(u.path[6:])
                    f = (WALL_CACHE / rel).resolve()
                    ok = str(f).startswith(str(WALL_CACHE.resolve())) and f.is_file() and f.suffix == ".jpg"
                    return self._send(200, f.read_bytes(), "image/jpeg") if ok else self._send(404, b"missing", "text/plain")
                if u.path == "/api/walls":
                    return self._json(app.walls())
                if u.path == "/api/trash":
                    return self._json(app.trash())
                return self._send(404, b"not found", "text/plain")
            except (ValueError, KeyError) as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/bye" and presence is not None and self._ok_host():              # the tab's closing beacon (sendBeacon cannot set the token header: it rides in the query)
                q = urllib.parse.parse_qs(u.query)
                if q.get("t", [""])[0] == token:
                    presence.bye(q.get("id", [""])[0])
                return self._send(204, b"", "text/plain")
            if not self._ok_host() or self.headers.get("X-G2-Token") != token:
                return self._send(403, b"bad token", "text/plain")
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if u.path == "/api/hb":
                    if presence is not None:
                        presence.beat(str(body.get("id", "")))
                    return self._json({"ok": True})
                if u.path == "/api/review/cancel":
                    return self._json(app.review_cancel(str(body["id"])))
                if u.path == "/api/review/apply":
                    return self._json(app.review_apply())
                if u.path == "/api/goals/edit":
                    return self._json(app.goal_edit(dict(body)))
                if u.path == "/api/goals/cancel":
                    return self._json(app.goal_edit_cancel(str(body["id"])))
                if u.path == "/api/goals/apply":
                    return self._json(app.goal_edits_apply())
                if u.path == "/api/walls/label":
                    return self._json(app.label_wall(str(body["path"]), str(body.get("label", "")), body.get("distance_in"), str(body.get("note", ""))))
                if u.path == "/api/walls/trash":
                    return self._json(app.trash_walls(list(body["paths"])))
                if u.path == "/api/walls/restore":
                    return self._json(app.restore_walls(list(body["paths"])))
                if u.path == "/api/walls/sync":
                    return self._json({"status": app.remote.sync_walls()})
                if u.path == "/api/delete":
                    return self._json(app.delete(body["kind"], int(body["id"])))
                if u.path == "/api/restore":
                    return self._json(app.restore(int(body["trash_id"])))
                if u.path == "/api/pictures/trash":
                    return self._json(app.trash_pictures(list(body["paths"])))
                if u.path == "/api/facts/add":
                    return self._json(app.add_fact(str(body["fact"]), int(body.get("importance", 3)), bool(body.get("core", False))))
                if u.path == "/api/facts/edit":
                    return self._json(app.edit_fact(int(body["id"]), body.get("fact"), body.get("importance"), body.get("core"), body.get("ts")))
                if u.path == "/api/observations/add":
                    return self._json(app.add_observation(str(body["caption"]), str(body.get("labels", ""))))
                if u.path == "/api/observations/edit":
                    return self._json(app.edit_observation(int(body["id"]), body.get("caption"), body.get("labels")))
                if u.path == "/api/pictures/name":
                    return self._json(app.name_pictures(list(body["paths"]), str(body["name"])))
                if u.path == "/api/pictures/label":
                    return self._json(app.dismiss_label(str(body["path"]), str(body["label"]), bool(body.get("restore", False))))
                if u.path == "/api/pictures/move":
                    return self._json(app.move_pictures([list(x) for x in body["pairs"]]))
                if u.path == "/api/pictures/room":
                    return self._json(app.set_rooms(dict(body["rooms"])))
                if u.path == "/api/pictures/person":
                    return self._json(app.mark_people(list(body["paths"]), bool(body["value"])))
                if u.path == "/api/pictures/promote":
                    return self._json(app.promote_pictures(list(body["paths"]), bool(body.get("value", True))))
                if u.path == "/api/pictures/restore":
                    return self._json(app.restore_pictures(list(body["paths"])))
                if u.path == "/api/sync":
                    return self._json(app.sync_now(start=bool(body.get("start", True))))
                if u.path == "/api/mic":
                    return self._json(app.mic(turn_on=bool(body.get("on", False))))
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
.labelsum{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:8px 0;color:var(--ink)}
.labelsum .sub{color:var(--ink2);font-size:.85em;margin-top:4px}
.divider{margin:18px 0 4px;padding-bottom:4px;border-bottom:2px solid var(--accent);color:var(--accent);font-weight:600;text-transform:uppercase;letter-spacing:.06em;font-size:.8em}
.tab[aria-selected=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
.bar{display:flex;gap:8px;align-items:center;margin-bottom:10px}.bar input{flex:1;min-width:0;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink);font:inherit}
button{font:inherit;cursor:pointer}.row{display:flex;gap:10px;align-items:flex-start;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:8px}
.main{flex:1;min-width:0;overflow-wrap:anywhere}.meta{color:var(--muted);font-size:.8rem;margin-top:2px}.q{color:var(--ink2)}
.x{flex:none;width:32px;height:32px;border-radius:6px;border:1px solid var(--line);background:var(--surface);color:var(--x);font-size:1.25rem;line-height:1}.x:hover{background:var(--xbg);border-color:var(--x)}
.btn{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:6px;padding:6px 12px}.btn.danger{color:var(--x);border-color:var(--x)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}.card{position:relative;background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.card img{width:100%;aspect-ratio:1;object-fit:contain;display:block;background:#000;cursor:zoom-in}.pbtn{position:absolute;left:6px;bottom:34px;background:rgba(255,255,255,.88);color:#13201f;border:1px solid var(--line);border-radius:4px;padding:1px 7px;font-size:.72rem}.nbtn{position:absolute;right:6px;bottom:34px;background:rgba(255,255,255,.88);color:#13201f;border:1px solid var(--line);border-radius:4px;padding:1px 7px;font-size:.72rem}.rbtn{position:absolute;right:56px;bottom:34px;background:rgba(255,255,255,.88);color:#13201f;border:1px solid var(--line);border-radius:4px;padding:1px 7px;font-size:.72rem}.rbtn.set{background:var(--accent);color:#fff}.isperson img{opacity:.35}.isperson .pbtn{background:#b83227;color:#fff}.badge{position:absolute;left:6px;top:6px;background:#b8860b;color:#fff;border-radius:4px;padding:1px 6px;font-size:.7rem}.lb{position:fixed;inset:0;background:rgba(0,0,0,.88);display:none;align-items:center;justify-content:center;z-index:9;cursor:zoom-out}.lb img{max-width:95vw;max-height:92vh;object-fit:contain;background:#000}.lb div{position:absolute;bottom:14px;left:0;right:0;text-align:center;color:#ddd;font-size:.85rem}.card .cap{padding:6px 8px;font-size:.78rem;color:var(--ink2)}
.card .x{position:absolute;top:6px;right:6px;background:rgba(255,255,255,.85)}.group{margin:16px 0 6px;font-weight:600;color:var(--ink2)}
.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:10px 14px;border-radius:8px;display:none;gap:12px;align-items:center;max-width:90vw}
.toast button{background:none;border:0;color:var(--bg);text-decoration:underline}.empty{color:var(--muted);padding:24px 0}
</style></head><body><div class="wrap">
<h1>G2 Review</h1><div class="sub" id="status">connecting to the Pi…</div><div class="sub" id="lastsync"></div>
<div class="tabs" role="tablist" id="tabs"></div>
<div class="bar"><input id="q" type="search" placeholder="Filter this tab"><button class="btn" id="refresh">Refresh</button><button class="btn" id="micon" style="display:none" title="G2's wake word is off (G2, mic off): turn it back on now">Mic on</button><span id="micstate" class="meta" style="margin-left:6px"></span><button class="btn" id="syncnow" title="Copy everything from the Pi to this Mac now: goal data, pictures, walk logs, wall pictures, the memory DB, the logs (a few minutes)">Sync from the Pi</button><span id="extra"></span></div>
<div id="list"></div></div><div class="lb" id="lb" onclick="this.style.display='none'"><img alt=""><div></div></div>
<div class="toast" id="toast"><span id="toastmsg"></span><button id="undo">Undo</button></div>
<script>
const TOKEN="__TOKEN__";const TABS=[["facts","Facts"],["exchanges","Conversations"],["observations","Observations"],["pictures","Pictures"],["looks","Looks"],["walls","Walls"],["goals","Goals"],["sync","Waiting to sync"],["trash","Trash"]];
let data=[],undoFn=null,timer=null,confirmAt=0;      // declared: confirmAt was read before it was ever set, so the Empty trash button threw and did nothing
let tab=(location.hash||"").replace("#","")||localStorage.getItem("g2tab")||"facts";if(!TABS.some(t=>t[0]===tab))tab="facts";
const $=s=>document.querySelector(s);
async function api(path,body){const o=body===undefined?{headers:{"X-G2-Token":TOKEN}}:{method:"POST",headers:{"X-G2-Token":TOKEN,"Content-Type":"application/json"},body:JSON.stringify(body)};
 const r=await fetch(path,o);const raw=await r.text();let j;try{j=JSON.parse(raw)}catch(e){if(r.status===403||/bad token/i.test(raw)){setTimeout(()=>location.reload(),1500);throw new Error("this page is out of date (the review server was restarted): reloading")}throw new Error(raw.slice(0,120)||r.statusText)}
 if(!r.ok||j.error)throw new Error(j.error||r.statusText);return j}
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
function toast(msg,undo){clearTimeout(window.ct);window.ct=setTimeout(refreshCounts,1500);$("#toastmsg").textContent=msg;undoFn=undo||null;$("#undo").style.display=undo?"":"none";$("#toast").style.display="flex";clearTimeout(timer);timer=setTimeout(()=>$("#toast").style.display="none",9000)}
$("#undo").onclick=async()=>{if(undoFn){try{await undoFn();toast("Restored")}catch(e){toast("Could not restore: "+e.message)}load()}};
let counts={};
async function refreshCounts(){try{counts=await api("/api/counts");drawTabs()}catch(e){}}
function drawTabs(){const t=$("#tabs");t.replaceChildren();for(const [k,n] of TABS){const b=el("button","tab",counts[k]===undefined?n:n+" ("+counts[k]+")");b.setAttribute("role","tab");b.setAttribute("aria-selected",k===tab);b.onclick=()=>{tab=k;localStorage.setItem("g2tab",k);$("#q").value="";drawTabs();load()};t.append(b)}}
function factTools(r){const d=el("div","");d.style.cssText="display:flex;gap:6px;align-items:center;flex:none";
 const e=el("button","btn","Edit");e.onclick=async()=>{const t=prompt("Edit this fact",r.fact);if(t===null||!t.trim()||t.trim()===r.fact)return;const old=r.fact;
  try{await api("/api/facts/edit",{id:r.id,fact:t.trim()});r.fact=t.trim();render();toast("Fact updated",async()=>{await api("/api/facts/edit",{id:r.id,fact:old});load()})}catch(x){toast("Failed: "+x.message)}};
 const s=el("select");for(let i=1;i<=5;i++){const o=el("option","",String(i));o.value=i;if(i===r.importance)o.selected=true;s.append(o)}s.title="Importance (1-5)";
 s.onchange=async()=>{try{await api("/api/facts/edit",{id:r.id,importance:+s.value});r.importance=+s.value}catch(x){toast("Failed: "+x.message)}};
 const c=el("button","btn",r.core?"Core \u2713":"Core");c.title="Core facts are always told to Claude";
 c.onclick=async()=>{try{await api("/api/facts/edit",{id:r.id,core:!r.core});r.core=r.core?0:1;render()}catch(x){toast("Failed: "+x.message)}};
 d.append(e,s,c);return d}
function obsTools(r){const d=el("div","");d.style.cssText="display:flex;gap:6px;align-items:center;flex:none";const e=el("button","btn","Edit");
 e.onclick=async()=>{const t=prompt("Edit what G2 saw",r.caption);if(t===null||!t.trim())return;const l=prompt("Detector labels for it (optional, comma separated)",r.labels||"");if(l===null)return;const oc=r.caption,ol=r.labels||"";
  try{await api("/api/observations/edit",{id:r.id,caption:t.trim(),labels:l});r.caption=t.trim();r.labels=l.trim();render();toast("Observation updated",async()=>{await api("/api/observations/edit",{id:r.id,caption:oc,labels:ol});load()})}catch(x){toast("Failed: "+x.message)}};
 d.append(e);return d}
function addObservationButton(){const b=el("button","btn","Add observation");b.onclick=async()=>{const t=prompt("What G2 saw (a sentence, for example: The dishwasher has a steel door with a black handle)");if(!t||!t.trim())return;const l=prompt("Detector labels for it (optional, comma separated)","");if(l===null)return;
  try{const r=await api("/api/observations/add",{caption:t.trim(),labels:l});toast("Observation added",async()=>{await api("/api/delete",{kind:"observations",id:r.id})});load()}catch(x){toast("Failed: "+x.message)}};return b}
function addFactButton(){const b=el("button","btn","Add fact");b.onclick=()=>window.factForm(null);return b}
function chip(text,onx){const c=el("span","chip",text+" ");c.style.cssText="display:inline-block;border:1px solid var(--line);border-radius:10px;padding:0 6px;margin:2px 4px 2px 0;font-size:.74rem;background:var(--surface)";
 const x=el("button","","\u00d7");x.title="Wrong: remove this tag (you can undo)";x.style.cssText="border:0;background:none;color:var(--x);cursor:pointer;padding:0 0 0 2px;font:inherit";x.onclick=(ev)=>{ev.stopPropagation();onx()};c.append(x);return c}
function picCaption(p){const d=el("div","cap",picLabel(p)+(p.room?" \u00b7 room: "+p.room:"")+" \u00b7 "+p.time+(p.detector.length?" \u00b7 sees: ":""));
 for(const l of p.detector){d.append(chip(l,async()=>{try{await api("/api/pictures/label",{path:p.path,label:l});p.detector=p.detector.filter(x=>x!==l);render();toast("Removed the tag: "+l,async()=>{await api("/api/pictures/label",{path:p.path,label:l,restore:true});p.detector=[...p.detector,l].sort();render()})}catch(e){toast("Failed: "+e.message)}}))}return d}
function obsLabels(r){const d=el("div","meta",r.ts+(r.labels?" \u00b7 detector: ":""));const labs=(r.labels||"").split(",").map(x=>x.trim()).filter(Boolean);
 for(const l of labs){d.append(chip(l,async()=>{const old=r.labels,nw=labs.filter(x=>x!==l).join(", ");try{await api("/api/observations/edit",{id:r.id,labels:nw});r.labels=nw;render();toast("Removed the tag: "+l,async()=>{await api("/api/observations/edit",{id:r.id,labels:old});r.labels=old;render()})}catch(e){toast("Failed: "+e.message)}}))}return d}
function picLabel(p){if(p.name)return p.name;if(!p.pose)return "";return p.pose==="after_bow"?"Survey stop":p.pose.replace(/_/g," ")}
async function setRooms(ps,room){room=(room||"").trim().toLowerCase();const m={};for(const p of ps)m[p.path]=room;try{const r=await api("/api/pictures/room",{rooms:m});if(room)window.lastRoom=room;for(const p of ps)p.room=room;render();toast(room?"Room set to "+room+" for "+ps.length+" picture(s)":"Room cleared",async()=>{await api("/api/pictures/room",{rooms:r.previous});for(const p of ps)p.room=r.previous[p.path]||"";render()})}catch(e){toast("Failed: "+e.message)}}
function xbtn(fn){const b=el("button","x","×");b.title="Delete (goes to the Trash; you can undo)";b.setAttribute("aria-label","Delete");b.onclick=fn;return b}
function text(r){return r.fact||r.caption||(r.user_text?"You: "+r.user_text:"")}
const TAB=Math.random().toString(36).slice(2);const beat=()=>{api("/api/hb",{id:TAB}).catch(()=>{})};beat();setInterval(beat,5000);       // tells the server this tab is open; closing the tab stops the server
addEventListener("pageshow",beat);addEventListener("pagehide",()=>{try{navigator.sendBeacon("/api/bye?t="+encodeURIComponent(TOKEN)+"&id="+TAB)}catch(e){}});
async function showSync(){try{const r=await api("/api/sync");const ls=$("#lastsync");ls.replaceChildren(document.createTextNode(r.running?"Syncing from the Pi… ":"Last copy from the Pi: "));
  for(const t of r.tasks){const sp=el("span","",t.task+" "+t.last_ok+(t.failed?" (failed)":"")+"   ");if(t.stale||t.failed){sp.style.color="var(--x)";sp.style.fontWeight="600";sp.title="older than it should be"}ls.append(sp)}
  if(r.last&&r.last.outcome!=="ok"&&!r.running){const w=el("div","","Last try "+r.last.when+": "+r.last.message);w.style.cssText="color:var(--x);font-weight:600;margin-top:2px";ls.append(w)}
  const b=$("#syncnow");b.disabled=r.running;b.textContent=r.running?"Syncing…":"Sync from the Pi";return r}catch(e){return null}}
async function showMic(){try{const m=await api("/api/mic",{on:false});$("#micstate").textContent=m.paused?"Wake word off: "+Math.ceil(m.minutes_left)+" min left (until "+m.until+")":"";$("#micon").style.display=m.paused?"":"none"}catch(e){$("#micstate").textContent=""}}
async function micOn(){try{await api("/api/mic",{on:true});toast("Wake word back on");showMic()}catch(e){toast("Failed: "+e.message)}}
async function syncNow(){try{const r=await api("/api/sync",{start:true});toast(r.started?"Sync started: a few minutes if the Pi is on":"A sync is already running");await showSync();
  const tick=async()=>{const s=await showSync();if(s&&s.running){setTimeout(tick,4000);return}const l=s&&s.last;
   const say=!l?"Sync finished: see ~/g2_logs/sync.log":l.outcome==="ok"?"Sync done: "+l.message:l.outcome==="partial"?"Sync finished with a problem: "+l.message:"Sync did not run: "+l.message;
   toast(say);load()};setTimeout(tick,3000)}catch(e){toast("Failed: "+e.message)}}
async function load(){const list=$("#list");$("#extra").replaceChildren();list.replaceChildren(el("div","empty","Loading…"));
 try{
  if(tab==="pictures"||tab==="looks"){data=await api("/api/pictures")}
  else if(tab==="walls"){data=await api("/api/walls")}
  else if(tab==="goals"){data=await api("/api/goals")}
  else if(tab==="trash"){data=await api("/api/trash")}
  else if(tab==="sync"){data=await api("/api/waiting")}
  else{data=await api("/api/list?kind="+tab+"&q="+encodeURIComponent($("#q").value))}
  try{window.reviewState=await api("/api/review/state")}catch(e){window.reviewState=null}
  $("#status").textContent="Showing the copy of G2's data on this Mac (works with the Pi off). Deleted records go to the Trash first; nothing is removed for good until you empty it.";
 }catch(e){$("#status").textContent="Problem: "+e.message;list.replaceChildren(el("div","empty",e.message));return}
 render();clearTimeout(window.ct);window.ct=setTimeout(refreshCounts,300)}
function fold(title,open){const d=document.createElement("details");d.open=!!open;const sm=document.createElement("summary");sm.textContent=title;sm.style.cssText="cursor:pointer;font-weight:600;color:var(--ink2);margin:10px 0 4px";d.append(sm);return d}
/*GOALS_UI*/
/*MEMORY_UI*/
function renderWalls(list,f){const onlyNew=!!window.wallsUnlabeled;const items=data.filter(p=>(!onlyNew||(p.src==="roam"&&!p.labelled))&&(!f||JSON.stringify(p).toLowerCase().includes(f)));const nun=data.filter(p=>p.src==="roam"&&!p.labelled).length;if(nun){const fb=el("button","btn",onlyNew?"Show all wall pictures":"Show only the "+nun+" roam pictures without a label");fb.onclick=()=>{window.wallsUnlabeled=!onlyNew;render()};list.append(fb)}if(!items.length){list.append(el("div","empty",onlyNew?"Every roam picture has a label.":"No wall pictures yet."));return}
 const sum=el("div","labelsum");sum.append(el("b","","Wall pictures: "),document.createTextNode(items.filter(p=>p.src==="recognition").length+" recognition shots, "+items.filter(p=>p.src==="roam").length+" kept in roams. Distances are in inches from the camera lens to the base of the wall. These are kept apart from the object pictures."));list.append(sum);
 const grid=el("div","grid");for(const p of items){const c=el("div","card");const im=el("img");im.loading="lazy";im.src="/wimg/"+p.path.split("/").map(encodeURIComponent).join("/")+"?t="+TOKEN;im.alt=p.label;
  im.onclick=()=>{const lb=$("#lb");lb.querySelector("img").src=im.src;lb.querySelector("div").textContent=p.label+(p.distance_in!=null?" \u00b7 "+p.distance_in+" in":"")+(p.note?" \u00b7 "+p.note:"");lb.style.display="flex"};
  const cap=el("div","meta",p.label+(p.distance_in!=null?" \u00b7 "+p.distance_in+" in":"")+(p.angle_deg?" \u00b7 "+p.angle_deg+" deg":"")+(p.set?" \u00b7 "+p.set:"")+(p.estimate?" \u00b7 the estimator read "+(p.estimate.nearest_in!=null?p.estimate.nearest_in+" in":"clear")+" ("+p.estimate.state+")":""));if(p.src==="roam"){const lb2=el("button","pbtn",p.labelled?"Relabel":"Label");lb2.title="Say what this picture shows (wall, door, corner, chair, ...) and, if you know it, the real distance in inches";lb2.onclick=async(ev)=>{ev.stopPropagation();const l=prompt("What does this show? (wall, door, corner, chair, box, nothing, ...)",p.labelled?p.label:"wall");if(l===null)return;const d=l.trim()?prompt("Real distance to it in inches (leave blank if you do not know)",p.distance_in!=null?String(p.distance_in):""):"";if(d===null)return;try{await api("/api/walls/label",{path:p.path,label:l,distance_in:d===""?null:d});load();toast(l.trim()?"Labelled: "+l.trim():"Label cleared")}catch(e){toast("Failed: "+e.message)}};c.append(lb2)}
  c.append(im,cap,xbtn(async()=>{try{await api("/api/walls/trash",{paths:[p.path]});data=data.filter(d=>d!==p);render();toast("Wall picture moved to the trash",async()=>{await api("/api/walls/restore",{paths:[p.path]});load()})}catch(e){toast("Failed: "+e.message)}}));
  if(p.flags&&p.flags.length)c.append(el("div","meta",p.flags.join("; ")));grid.append(c)}list.append(grid)}
function render(){const list=$("#list"),f=$("#q").value.toLowerCase();list.replaceChildren();if(tab!=="goals"&&tab!=="sync"&&window.reviewPanel)window.reviewPanel(list);if(tab==="walls"){renderWalls(list,f);return}if(tab==="sync"){window.renderSync(list);return}if(tab==="goals"){renderGoals(list,f);return}if(tab==="facts"){$("#extra").replaceChildren(addFactButton());window.renderFacts(list,f);return}if(tab==="observations")$("#extra").replaceChildren(addObservationButton());
 if(tab==="pictures"||tab==="looks"){const showAll=!!window.showFiltered;const filteredOut=data.filter(p=>p.group!=="looks"&&["rejected","duplicate","people"].includes(p.status)).length;const items=data.filter(p=>(!window.noRoomOnly||tab==="looks"||!p.room)&&((p.group==="looks")===(tab==="looks"))&&(tab==="looks"||showAll||!["rejected","duplicate","people"].includes(p.status))&&(!f||JSON.stringify(p).toLowerCase().includes(f)));if(tab==="pictures"&&filteredOut){const fb=el("button","btn",showAll?"Hide the "+filteredOut+" filtered (bad quality, duplicates, people)":"Show the "+filteredOut+" filtered (bad quality, duplicates, people)");fb.onclick=()=>{window.showFiltered=!showAll;render()};list.append(fb);
  const bad=data.filter(p=>p.group!=="looks"&&p.group!=="named"&&["rejected","duplicate","people"].includes(p.status)),keepNamed=filteredOut-bad.length;      // user, 2026-11-01: flagged pictures are deleted, not kept hidden; ones you named stay
  if(bad.length){const db=el("button","btn danger","Delete the "+bad.length+" filtered pictures");db.style.marginLeft="8px";db.title="Moves them to the Trash (Undo brings them back; the Trash empties for good with Empty trash)"+(keepNamed?". The "+keepNamed+" you have named are kept.":"");db.onclick=async()=>{const ps=bad.map(q=>q.path);try{await api("/api/pictures/trash",{paths:ps});data=data.filter(d=>!ps.includes(d.path));render();toast(ps.length+" filtered pictures moved to the Trash",async()=>{await api("/api/pictures/restore",{paths:ps});load()})}catch(e){toast("Failed: "+e.message)}};list.append(db)}}if(tab==="pictures"){const nr=data.filter(p=>p.group!=="looks"&&!p.room).length,rr={};for(const p of data)if(p.room)rr[p.room]=(rr[p.room]||0)+1;const rs=el("div","labelsum");rs.append(el("b","","Rooms: "),document.createTextNode(Object.keys(rr).length?Object.keys(rr).sort().map(k=>k+" ("+rr[k]+")").join(" \u00b7 "):"none set yet"));rs.append(el("div","sub",nr+" pictures without a room. Use Room on a picture, or Set the room of all in a group header."));list.append(rs);const nb2=el("button","btn",window.noRoomOnly?"Show all pictures":"Show only the "+nr+" without a room");nb2.onclick=()=>{window.noRoomOnly=!window.noRoomOnly;render()};list.append(nb2)}
  if(!items.length){list.append(el("div","empty",tab==="looks"?"No look pictures.":window.noRoomOnly?"Every picture has a room.":"No pictures yet."));return}
  const groups={};for(const p of items){const g=p.group==="named"?"Named: "+p.folder:(p.group==="looks"?"Looks "+p.folder:"Not labeled");(groups[g]=groups[g]||[]).push(p)}
  const fname=p=>p.path.split("/").pop().toLowerCase();for(const g of Object.keys(groups))groups[g].sort((a,b)=>fname(a).localeCompare(fname(b)));       // A to Z by file name inside every group (classes first, then the unlabeled images, both alphabetical)
  const named=Object.keys(groups).filter(g=>g.startsWith("Named: ")).sort((x,y)=>x.localeCompare(y,undefined,{sensitivity:"base"})),survey=Object.keys(groups).filter(g=>!g.startsWith("Named: ")).sort((x,y)=>x.localeCompare(y)).reverse();
  const nl=named.reduce((n,g)=>n+groups[g].length,0),nu=survey.reduce((n,g)=>n+groups[g].length,0);
  const sum=el("div","labelsum");sum.append(el("b","","Labels so far: "));
  sum.append(document.createTextNode(named.length?named.map(g=>g.slice(7)+" ("+groups[g].length+")").join(" \u00b7 "):"none yet"));
  sum.append(el("div","sub",nl+" labeled, "+nu+" not labeled yet. Name a picture with its Name button; labeled pictures are listed first."));list.append(sum);
  const order=[...named,...survey];if(named.length&&survey.length){order.splice(named.length,0,"\u0000divider")}
  window.closedSections=window.closedSections||{};let sec="Labeled";const isClosed=n=>window.closedSections[n]!==false;      // the two sections (Labeled, Not labeled yet) fold too (user, 2026-11-01); both start collapsed
  const divider=name=>{const d=el("div","divider",(isClosed(name)?"\u25B8 ":"\u25BE ")+name);d.style.cursor="pointer";d.setAttribute("role","button");d.tabIndex=0;const flip=()=>{window.closedSections[name]=!isClosed(name);render()};d.onclick=flip;d.onkeydown=ev=>{if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();flip()}};list.append(d)};
  for(const g of order){if(g==="\u0000divider"){sec="Not labeled yet";divider(sec);continue}
   if(g===named[0])divider("Labeled");else if(!named.length&&g===survey[0])sec="Not labeled yet";
   const secOpen=!isClosed(sec);
   {const gh=el("div","group",g+" ("+groups[g].length+(g.startsWith("Named: ")?" \u00b7 "+groups[g].filter(q=>q.promoted).length+" in the training data":"")+(groups[g].some(q=>q.room)?" \u00b7 "+groups[g].filter(q=>q.room).length+" with a room":"")+") ");const gb=el("button","btn","Set the room of all "+groups[g].length);gb.style.cssText="margin-left:8px;padding:1px 8px;font-size:.78rem";gb.onclick=async()=>{const r=prompt("Which room are all "+groups[g].length+" pictures in this group from? (you can change single ones afterwards)",window.lastRoom||"");if(r===null||!r.trim())return;await setRooms(groups[g],r)};gh.append(gb);list.append(gh);const grid=el("div","grid");
   {window.openGroups=window.openGroups||{};if(!(g in window.openGroups))window.openGroups[g]=!g.startsWith("Named: ");      // named groups start collapsed, the unnamed ones open (user, 2026-11-01); the choice survives a redraw
    const caret=el("span","caret");const sync=()=>{const o=window.openGroups[g];caret.textContent=o?"\u25BE ":"\u25B8 ";grid.style.display=o&&secOpen?"":"none";gh.style.display=secOpen?"":"none";gh.setAttribute("aria-expanded",o)};gh.prepend(caret);gh.style.cursor="pointer";gh.setAttribute("role","button");gh.tabIndex=0;
    const flip=ev=>{if(ev.target.closest&&ev.target.closest("button"))return;window.openGroups[g]=!window.openGroups[g];sync()};gh.onclick=flip;gh.onkeydown=ev=>{if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();flip(ev)}};sync()}

   for(const p of groups[g]){const c=el("div","card");const im=el("img");im.loading="lazy";im.src="/img/"+p.path.split("/").map(encodeURIComponent).join("/")+"?t="+TOKEN;im.alt=picLabel(p)||"picture";
    im.onclick=()=>{const lb=$("#lb");lb.querySelector("img").src=im.src;lb.querySelector("div").textContent=picLabel(p)+" \u00b7 "+p.time+(p.cut_off?" \u00b7 cut off by the camera: only the top part is real, the rest is gray":"");lb.style.display="flex"};if(p.cut_off)c.append(el("div","badge","cut off"));if(["rejected","duplicate","people"].includes(p.status)){const sb=el("div","badge",p.status==="duplicate"?"duplicate":p.status==="people"?"person":"filtered: "+p.reason);sb.title=p.reason||"";c.append(sb)}if(p.person)c.classList.add("isperson");
    const pb=el("button","pbtn",p.person?"Person \u2713":"Person");pb.title=p.person?"Flagged as a person. Click to remove the flag":"Flag this picture: a person is in it (it is kept out of the object library)";pb.onclick=async(ev)=>{ev.stopPropagation();try{await api("/api/pictures/person",{paths:[p.path],value:!p.person});p.person=!p.person;render();const now=p.person;toast(now?"Flagged: a person is in it":"Person flag removed",async()=>{await api("/api/pictures/person",{paths:[p.path],value:!now});p.person=!now;render()})}catch(e){toast("Failed: "+e.message)}};c.append(pb);
    if(tab==="pictures"&&p.group==="named"&&!p.promoted){const pr=el("button","pbtn","Promote");pr.title="Add this labelled picture to the training data (it was set aside or taken out)";pr.onclick=async(ev)=>{ev.stopPropagation();try{const r=await api("/api/pictures/promote",{paths:[p.path],value:!p.promoted});p.promoted=!p.promoted;render();const g=r.gallery||{};toast(!p.promoted?"Taken out of the training data (it stays in the robot's gallery)":g.error?"Promoted to the training data; the robot's gallery could not be reached: "+g.error:g.deferred?"Promoted; the robot's gallery learns it at the next exploration start":(g.conflicts&&g.conflicts.length)?"Promoted, but the gallery has a look-alike with a different name: not loaded":"Promoted: in the training data and the robot's gallery")}catch(e){toast("Failed: "+e.message)}};c.append(pr)}
    if(p.group!=="looks"){const rb=el("button","rbtn"+(p.room?" set":""),p.room?"Room: "+p.room:"Room");rb.title="Which room is this picture from? (kitchen, hallway, ...). Used for G2's place memory; leave empty to clear";rb.onclick=async(ev)=>{ev.stopPropagation();const r=prompt("Which room is this picture from? (empty clears it)",p.room||window.lastRoom||"");if(r===null)return;await setRooms([p],r)};c.append(rb)}
    const nb=el("button","nbtn","Name");nb.title="Name what is in this picture (it moves into that object's folder in the library)";nb.onclick=async(ev)=>{ev.stopPropagation();const nm=prompt("What is this? (for example: dishwasher)",p.name||window.lastName||"");if(!nm||!nm.trim())return;
     try{const r=await api("/api/pictures/name",{paths:[p.path],name:nm.trim()});window.lastName=nm.trim();toast("Named: "+nm.trim(),async()=>{await api("/api/pictures/move",{pairs:r.named.map(m=>[m.to,m.from])})});load()}catch(e){toast("Failed: "+e.message)}};c.append(nb);
    c.append(im,xbtn(async()=>{try{await api("/api/pictures/trash",{paths:[p.path]});data=data.filter(d=>d!==p);render();toast("Picture moved to the Trash",async()=>{await api("/api/pictures/restore",{paths:[p.path]})})}catch(e){toast("Failed: "+e.message)}}));
    c.append(picCaption(p));grid.append(c)}list.append(grid)}}return}
 if(tab==="trash"){const m=data.memory.map(t=>({t,txt:t.kind+": "+(t.row.fact||t.row.caption||t.row.user_text||"")})),pics=data.pictures;
  const b=el("button","btn danger","Empty trash");b.onclick=async()=>{if(Date.now()-confirmAt>4000){confirmAt=Date.now();b.textContent="Click again to delete for good";return}
   try{const r=await api("/api/empty-trash",{});toast("Deleted for good: "+r.memory.removed+" records, "+(r.pictures.removed+((r.walls||{}).removed||0))+" pictures");load()}catch(e){toast("Failed: "+e.message)}};$("#extra").append(b);
  if(!m.length&&!pics.length)list.append(el("div","empty","The trash is empty."));
  for(const {t,txt} of m){const row=el("div","row"),main=el("div","main");main.append(el("div","",txt),el("div","meta","deleted "+t.deleted_at));const r=el("button","btn","Restore");
   r.onclick=async()=>{try{await api("/api/restore",{trash_id:t.trash_id});toast("Restored");load()}catch(e){toast("Could not restore: "+e.message)}};row.append(main,r);list.append(row)}
  for(const p of pics){const row=el("div","row"),main=el("div","main");main.append(el("div","","picture "+p.path),el("div","meta",Math.round(p.bytes/1000)+" KB"));const r=el("button","btn","Restore");
   r.onclick=async()=>{try{await api("/api/pictures/restore",{paths:[p.path]});toast("Restored");load()}catch(e){toast("Could not restore: "+e.message)}};row.append(main,r);list.append(row)}return}
 const items=data.filter(r=>!f||JSON.stringify(r).toLowerCase().includes(f));if(!items.length){list.append(el("div","empty","Nothing here."));return}
 for(const r of items){const row=el("div","row"),main=el("div","main");
  if(tab==="exchanges"){main.append(el("div","",r.user_text),el("div","q",r.assistant_text),el("div","meta",r.ts+(r.actions?" · "+r.actions:"")))}
  else if(tab==="observations"){main.append(el("div","",r.caption),obsLabels(r))}
  else{const meta=el("div","meta","#"+r.id+" · ");const db=el("button","","");db.textContent=r.ts.slice(0,10);db.title="Click to change this fact's date";db.style.cssText="border:0;background:none;color:var(--accent);cursor:pointer;font:inherit;padding:0;text-decoration:underline dotted";
   db.onclick=async()=>{const t=prompt("Date for this fact (2026-10-10, or 2026-10-10 18:30)",r.ts.slice(0,10));if(t===null||!t.trim()||t.trim()===r.ts.slice(0,10))return;const old=r.ts.slice(0,19);try{await api("/api/facts/edit",{id:r.id,ts:t.trim()});load();toast("Date changed",async()=>{await api("/api/facts/edit",{id:r.id,ts:old});load()})}catch(x){toast("Failed: "+x.message)}};
   meta.append(db,document.createTextNode((r.core?" \u00b7 core":"")+" \u00b7 importance "+r.importance+" (change it with the number box)"));main.append(el("div","",r.fact),meta)}
  row.append(main);if(tab==="facts")row.append(factTools(r));if(tab==="observations")row.append(obsTools(r));row.append(xbtn(async()=>{try{const t=await api("/api/delete",{kind:tab,id:r.id});data=data.filter(d=>d!==r);render();toast("Moved to the Trash",async()=>{await api("/api/restore",{trash_id:t.trash_id})})}catch(e){toast("Failed: "+e.message)}}));list.append(row)}}
window.addEventListener("hashchange",()=>{const h=location.hash.replace("#","");if(TABS.some(t=>t[0]===h)){tab=h;drawTabs();load()}});
$("#q").oninput=()=>{if(tab==="facts"||tab==="exchanges"||tab==="observations"){clearTimeout(window.qt);window.qt=setTimeout(load,300)}else render()};$("#refresh").onclick=load;$("#syncnow").onclick=syncNow;$("#micon").onclick=micOn;drawTabs();load();showSync();showMic();setInterval(showMic,60000);
</script></body></html>"""
PAGE = PAGE.replace("/*GOALS_UI*/", (Path(__file__).resolve().parent / "g2_goals_ui.js").read_text())          # the Goals tab's drawing code lives in its own file
PAGE = PAGE.replace("/*MEMORY_UI*/", (Path(__file__).resolve().parent / "g2_memory_ui.js").read_text())        # ... and so does the Facts tab's


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
    presence = Presence()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(App(MirrorRemote(pi)), token, port, presence))
    PIDFILE.write_text(str(os.getpid()))

    def watch():                                                # the last tab closed: stop (the same as `g2pics stop`)
        while True:
            time.sleep(1.0)
            if presence.due():
                srv.shutdown()
                return
    threading.Thread(target=watch, daemon=True).start()
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
