"""Saves the pictures G2 takes while exploring, with a JSON sidecar each, for building a training / recognition set.

    ~/.local/share/g2/explore_pictures/survey/<YYYYMMDD>/<pose>_<time>.jpg (+ .json)      the survey stops (look down, look up)
    ~/.local/share/g2/explore_pictures/named/<name>/<name>_<time>.jpg (+ .json)           a picture you named by voice ("this is a mug")

`ExplorationPictureSaver(source, root)` is the callable the camera binding calls with a kind: "look_down", "look_up" or "name:<name>". `source` has a
`snapshot()` that returns a `vision.snapshot.Snapshot` (the detection feed's own port, see `BackgroundFrameSource.snapshot`). One USB request to the
camera; no network and no API call. The pictures stay on the Pi; `tools/curate_exploration.py` processes them on the Mac after you copy them.
The sidecar carries the pose, the time, what the on-camera detector saw (label, score, box) and the picture's brightness, so the processing step can
filter without opening every picture."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("g2.exploration_pictures")

DEFAULT_ROOT = "~/.local/share/g2/explore_pictures"
_SLUG = re.compile(r"[^a-z0-9\-]+")


def slug(text: str) -> str:
    return _SLUG.sub("_", (text or "").lower().replace(" ", "-")).strip("_") or "x"


class ExplorationPictureSaver:
    def __init__(self, source, root: str = DEFAULT_ROOT, *, clock=time.time, warn_mb: float = 2000.0, on_saved=None,
                 survey_distance: int = 12, named_distance: int = 3):
        self._source = source
        self._root = Path(os.path.expanduser(root))
        self._clock = clock
        self._warn_mb = warn_mb
        self._on_saved = on_saved                  # called with the saved path (a shutter tick, a counter)
        self._survey_distance, self._named_distance = survey_distance, named_distance
        self._hashes: dict = {}                    # (folder, prefix) -> hashes of the pictures already kept there
        self.duplicates = 0
        self.count = 0
        self.last_path: str | None = None
        self.last_kind: str | None = None

    def folder_for(self, kind: str, now: float) -> Path:
        if kind.startswith("name:"):
            return self._root / "named" / slug(kind[5:])
        return self._root / "survey" / time.strftime("%Y%m%d", time.localtime(now))

    def __call__(self, kind) -> str | None:
        kind = str(kind or "picture")
        snap = self._source.snapshot()
        if snap is None:
            log.warning("no picture for %s (the camera did not answer)", kind)
            return None
        now = self._clock()
        folder = self.folder_for(kind, now)
        folder.mkdir(parents=True, exist_ok=True)
        pose = "named" if kind.startswith("name:") else kind
        prefix = slug(kind[5:]) if kind.startswith("name:") else pose
        if self._is_duplicate(folder, prefix, snap.jpeg, self._named_distance if kind.startswith("name:") else self._survey_distance):
            self.duplicates += 1
            log.info("picture not kept: a near-duplicate of one already saved (%s)", kind)
            return None
        base = prefix + time.strftime("_%H%M%S", time.localtime(now)) + f"_{int((now % 1) * 1000):03d}"
        path = folder / (base + ".jpg")
        path.write_bytes(snap.jpeg)
        meta = {"file": path.name, "kind": kind, "pose": pose, "name": kind[5:] if kind.startswith("name:") else None,
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "width": snap.width, "height": snap.height,
                "detections": [{"label": d[0], "score": round(float(d[1]), 3), "cx": round(float(d[2]), 3), "cy": round(float(d[3]), 3),
                                "w": round(float(d[4]), 3), "h": round(float(d[5]), 3)} for d in (snap.detections or [])]}
        try:
            from .snapshot import exposure_stats
            st = exposure_stats(snap.jpeg)
            meta["exposure"] = None if st is None else {"mean": round(st.mean, 1), "clip_high": round(st.clip_high, 4), "clip_low": round(st.clip_low, 4)}
        except Exception:  # noqa: BLE001 -- Pillow may be missing on the Pi
            meta["exposure"] = None
        path.with_suffix(".json").write_text(json.dumps(meta))
        self.count += 1
        self.last_path, self.last_kind = str(path), kind
        log.info("picture saved: %s (%s)", path, kind)
        self._check_size()
        if self._on_saved:
            try:
                self._on_saved(str(path))
            except Exception:  # noqa: BLE001
                log.debug("on_saved hook failed", exc_info=True)
        return str(path)

    def _is_duplicate(self, folder: Path, prefix: str, jpeg: bytes, max_distance: int) -> bool:
        """The ONLY reason a picture is not kept (retention policy 2026-10-07: nothing is deleted except duplicates): its 256-bit average hash is within
        `max_distance` bits of one already saved for the same pose (or name) in this folder, the earliest of a cluster being kept. Fails open: without
        Pillow nothing is ever treated as a duplicate."""
        try:
            from .pictures import ahash, hamming
            h = ahash(jpeg)
        except Exception:  # noqa: BLE001
            return False
        key = (str(folder), prefix)
        if key not in self._hashes:                         # first use: learn the pictures already on disk for this pose / name
            known = []
            for f in sorted(folder.glob(prefix + "_*.jpg")):
                try:
                    known.append(ahash(f.read_bytes()))
                except Exception:  # noqa: BLE001
                    pass
            self._hashes[key] = known
        if any(hamming(h, k) <= max_distance for k in self._hashes[key]):
            return True
        self._hashes[key].append(h)
        return False

    def _check_size(self) -> None:
        if self.count % 25:
            return
        try:
            total = sum(f.stat().st_size for f in self._root.rglob("*") if f.is_file()) / 1e6
            if total > self._warn_mb:
                log.warning("exploration pictures use %.0f MB (warning at %.0f MB): copy them off and clear %s", total, self._warn_mb, self._root)
        except OSError:
            pass


def status(root: str = DEFAULT_ROOT, newest: int = 8) -> str:
    """A text summary of the saved exploration pictures: totals, per pose and day, per named object, disk use and the newest few."""
    base = Path(os.path.expanduser(root))
    if not base.exists():
        return f"no exploration pictures yet ({base})"
    jpgs = sorted(base.rglob("*.jpg"), key=lambda f: f.stat().st_mtime)
    mb = sum(f.stat().st_size for f in jpgs) / 1e6
    lines = [f"{len(jpgs)} pictures, {mb:.1f} MB in {base}"]
    survey: dict = {}
    for f in (base / "survey").rglob("*.jpg") if (base / "survey").exists() else []:
        pose = f.name.split("_")[0] + "_" + f.name.split("_")[1]
        survey.setdefault(f.parent.name, {}).setdefault(pose, 0)
        survey[f.parent.name][pose] += 1
    for day in sorted(survey):
        lines.append(f"  survey {day}: " + ", ".join(f"{p} {n}" for p, n in sorted(survey[day].items())))
    named = base / "named"
    if named.exists():
        for d in sorted(p for p in named.iterdir() if p.is_dir()):
            lines.append(f"  named {d.name}: {len(list(d.glob('*.jpg')))}")
    lines.append("newest:")
    for f in jpgs[-newest:][::-1]:
        meta = {}
        try:
            meta = json.loads(f.with_suffix(".json").read_text())
        except (OSError, ValueError):
            pass
        ex = (meta.get("exposure") or {}).get("mean")
        det = ",".join(sorted({d["label"] for d in meta.get("detections", [])})) or "-"
        lines.append(f"  {meta.get('time', time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(f.stat().st_mtime)))}  {f.parent.name}/{f.name}"
                     f"  brightness {ex if ex is not None else '?'}  detector: {det}")
    try:
        from ..config import settings
        if settings.vision_save_dir and Path(settings.vision_save_dir).exists():
            n = len(list(Path(settings.vision_save_dir).glob("look_*.jpg")))
            lines.append(f"voice-service look pictures: {n} in {settings.vision_save_dir}")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)


def _base(root: str) -> Path:
    return Path(os.path.expanduser(root))


def trash_root(root: str = DEFAULT_ROOT) -> Path:
    b = _base(root)
    return b.with_name(b.name + "_trash")


def _inside(base: Path, rel: str) -> Path:
    """`rel` (a path under `base`, as list_pictures() reports it) resolved and checked: it must stay inside `base` and be a .jpg."""
    p = (base / rel).resolve()
    if base.resolve() not in p.parents or p.suffix.lower() != ".jpg":
        raise ValueError(f"not a picture inside {base}: {rel}")
    return p


def list_pictures(root: str = DEFAULT_ROOT) -> list[dict]:
    """Every saved picture, newest first: its path under the root, what it is (survey pose or named object) and what its sidecar says."""
    base = _base(root)
    out = []
    for f in sorted(base.rglob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True) if base.exists() else []:
        meta = {}
        try:
            meta = json.loads(f.with_suffix(".json").read_text())
        except (OSError, ValueError):
            pass
        rel = str(f.relative_to(base))
        out.append({"path": rel, "group": rel.split("/")[0], "folder": f.parent.name, "pose": meta.get("pose"), "name": meta.get("name"),
                    "time": meta.get("time") or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime)),
                    "brightness": (meta.get("exposure") or {}).get("mean"), "detector": sorted({d["label"] for d in meta.get("detections", [])} - set(meta.get("dismissed_labels", []))),
                    "dismissed": sorted(set(meta.get("dismissed_labels", []))),
                    "bytes": f.stat().st_size})
    return out


def trash_pictures(root: str, rels: list[str]) -> list[str]:
    """Move pictures (and their sidecars) into the trash folder next to the root, keeping their relative paths so `restore_pictures` can put them back.
    Nothing is deleted. Returns the paths moved."""
    base, tr, moved = _base(root), trash_root(root), []
    for rel in rels:
        src = _inside(base, rel)
        if not src.exists():
            continue
        dst = tr / src.relative_to(base.resolve())
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        side = src.with_suffix(".json")
        if side.exists():
            side.replace(dst.with_suffix(".json"))
        moved.append(rel)
    return moved


def restore_pictures(root: str, rels: list[str]) -> list[str]:
    base, tr, back = _base(root), trash_root(root), []
    for rel in rels:
        dst = _inside(base, rel)
        src = tr / dst.relative_to(base.resolve())
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        if src.with_suffix(".json").exists():
            src.with_suffix(".json").replace(dst.with_suffix(".json"))
        back.append(rel)
    return back


def name_pictures(root: str, name: str, rels: list[str]) -> list[dict]:
    """Give pictures a name by hand (the review page): each picture and its sidecar move to `named/<name>/` (where a voice naming would have put it) and the sidecar says so.
    Returns [{"from": rel, "to": rel}]; `move_pictures` puts them back (the page's Undo). An unnamed survey picture and an already named one both work (a rename)."""
    from ..behavior.survey import clean_name
    nm = clean_name(name)
    if not nm:
        raise ValueError("give a name (letters, numbers, spaces and hyphens)")
    base, out = _base(root), []
    for rel in rels:
        src = _inside(base, rel)
        if not src.exists():
            continue
        dst_dir = base / "named" / slug(nm)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        n = 2
        while dst.exists() and dst != src:
            dst = dst_dir / f"{src.stem}_{n}{src.suffix}"
            n += 1
        meta = {}
        try:
            meta = json.loads(src.with_suffix(".json").read_text())
        except (OSError, ValueError):
            pass
        meta.update(name=nm, pose="named", named_by="hand")
        if dst != src:
            src.replace(dst)
            if src.with_suffix(".json").exists():
                src.with_suffix(".json").unlink()
        dst.with_suffix(".json").write_text(json.dumps(meta, indent=1))
        out.append({"from": rel, "to": str(dst.relative_to(base))})
    return out


def set_label_dismissed(root: str, rel: str, label: str, dismissed: bool = True) -> dict:
    """Flag one detector label on a picture as wrong (the detector called a bare floor a dog), or put it back. The detection record itself is kept; the picture's sidecar lists the
    dismissed labels and the page stops showing them. Returns the picture's labels now."""
    path = _inside(_base(root), rel).with_suffix(".json")
    meta = {}
    try:
        meta = json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    gone = set(meta.get("dismissed_labels", []))
    (gone.add if dismissed else gone.discard)(label)
    meta["dismissed_labels"] = sorted(gone)
    path.write_text(json.dumps(meta, indent=1))
    return {"path": rel, "dismissed": sorted(gone), "detector": sorted({d["label"] for d in meta.get("detections", [])} - gone)}


def move_pictures(root: str, pairs: list[tuple[str, str]]) -> list[dict]:
    """Move pictures (with their sidecars) from one path under the root to another: the Undo of `name_pictures`."""
    base, out = _base(root), []
    for src_rel, dst_rel in pairs:
        src, dst = _inside(base, src_rel), _inside(base, dst_rel)
        if not src.exists() or dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        if src.with_suffix(".json").exists():
            src.with_suffix(".json").replace(dst.with_suffix(".json"))
        out.append({"from": src_rel, "to": dst_rel})
    return out


def list_trash(root: str = DEFAULT_ROOT) -> list[dict]:
    tr = trash_root(root)
    out = []
    for f in sorted(tr.rglob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True) if tr.exists() else []:
        out.append({"path": str(f.relative_to(tr)), "bytes": f.stat().st_size})
    return out


def empty_trash(root: str = DEFAULT_ROOT) -> int:
    """The only permanent delete of a picture (never automatic). Returns how many pictures were removed."""
    import shutil
    tr = trash_root(root)
    n = len(list(tr.rglob("*.jpg"))) if tr.exists() else 0
    if tr.exists():
        shutil.rmtree(tr)
    return n


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Summarize and manage the pictures G2 saved while exploring")
    ap.add_argument("--root", default=os.environ.get("G2_EXPLORE_PICTURES_DIR", DEFAULT_ROOT))
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    sub.add_parser("list").set_defaults(json=True)
    for name in ("trash", "restore"):
        sp = sub.add_parser(name)
        sp.add_argument("paths", nargs="+")
    sp = sub.add_parser("name")
    sp.add_argument("name")
    sp.add_argument("paths", nargs="+")
    sp = sub.add_parser("label")
    sp.add_argument("path")
    sp.add_argument("label")
    sp.add_argument("--restore", action="store_true")
    sp = sub.add_parser("move")
    sp.add_argument("pairs", nargs="+", help="SRC:DST relative paths")
    sub.add_parser("trash-list")
    sub.add_parser("empty-trash")
    a = ap.parse_args(argv)
    if a.cmd in (None, "status"):
        print(status(a.root))
    elif a.cmd == "list":
        print(json.dumps(list_pictures(a.root)))
    elif a.cmd == "trash":
        print(json.dumps({"moved": trash_pictures(a.root, a.paths)}))
    elif a.cmd == "restore":
        print(json.dumps({"restored": restore_pictures(a.root, a.paths)}))
    elif a.cmd == "name":
        print(json.dumps({"named": name_pictures(a.root, a.name, a.paths)}))
    elif a.cmd == "label":
        print(json.dumps(set_label_dismissed(a.root, a.path, a.label, not a.restore)))
    elif a.cmd == "move":
        print(json.dumps({"moved": move_pictures(a.root, [tuple(x.split(":", 1)) for x in a.pairs])}))
    elif a.cmd == "trash-list":
        print(json.dumps(list_trash(a.root)))
    else:
        print(json.dumps({"removed": empty_trash(a.root)}))


if __name__ == "__main__":
    main()
