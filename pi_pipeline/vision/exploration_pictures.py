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


def _decodes(jpeg: bytes) -> bool:
    """True if the JPEG decodes completely (a picture cut off by the camera's small buffer fails here). Without Pillow nothing is checked."""
    try:
        from PIL import Image
    except ImportError:
        return True
    try:
        import io
        Image.open(io.BytesIO(jpeg)).load()
        return True
    except Exception:  # noqa: BLE001
        return False


def _exposure_cost(jpeg: bytes) -> float:
    try:
        from .snapshot import exposure_score, exposure_stats
        st = exposure_stats(jpeg)
        return 9.0 if st is None else exposure_score(st)
    except Exception:  # noqa: BLE001
        return 9.0


def _badly_exposed(jpeg: bytes) -> bool:
    """Brightness over 170 (0..255, target about 100) or more than 5% blown out: the picture is worth one more try (a dark one is kept, its brightness is in the sidecar). Wider than the wall pictures (85 to 140): a retake is a second warm-up, and the
    stop was 15 s long on 2026-10-10 with a picture at brightness 64 retaken for nothing."""
    try:
        from .snapshot import exposure_stats
        st = exposure_stats(jpeg)
    except Exception:  # noqa: BLE001
        return False
    return st is not None and (st.mean > 170.0 or st.clip_high > 0.05)           # too bright only: a retake of a dark picture is dark again (a dim room, 2026-10-10: brightness 30, retaken, still 30) and costs another warm-up


class ExplorationPictureSaver:
    def __init__(self, source, root: str = DEFAULT_ROOT, *, clock=time.time, warn_mb: float = 2000.0, on_saved=None,
                 survey_distance: int = 12, named_distance: int = 3, prep_every_s: float = 0.0, wait_still=None, on_failure=None, on_survey_stop=None):
        self._source = source
        self._prep_every_s = prep_every_s           # the camera prep (the throwaway frames that let auto-exposure settle) is done for the first picture and again after this long (0 = every picture)
        self._last_prep: float | None = None
        self._wait_still = wait_still              # callable() -> True (still) | False (still swaying at the timeout) | None (no IMU): waited for right before each picture, to limit camera shake
        self._on_failure = on_failure              # callable(why): the wrong-answer signal when no picture could be taken
        self._root = Path(os.path.expanduser(root))
        self._clock = clock
        self._warn_mb = warn_mb
        self._on_saved = on_saved                  # called with the saved path (a shutter tick, a counter)
        self._on_survey_stop = on_survey_stop      # called as (path or None, sidecar dict, jpeg bytes) for every survey-stop picture (kind 'after_bow'), also a near-duplicate that was not kept: the place log (behavior/place_log.py)
        self._survey_distance, self._named_distance = survey_distance, named_distance
        self._hashes: dict = {}                    # (folder, prefix) -> hashes of the pictures already kept there
        self.duplicates = 0
        self.count = 0
        self.last_path: str | None = None
        self.last_kind: str | None = None

    def _take(self, prep: bool):
        try:
            return self._source.snapshot() if prep else self._source.snapshot(settle=0)       # no prep: the picture right after the mode switch
        except TypeError:                                                                       # a source whose snapshot() takes no settle argument
            return self._source.snapshot()

    def folder_for(self, kind: str, now: float) -> Path:
        if kind.startswith("name:"):
            return self._root / "named" / slug(kind[5:])
        if kind.startswith("look_"):                                     # throwaway look pictures (left / right): their own folder, never the recognition set
            return self._root / "looks" / time.strftime("%Y%m%d", time.localtime(now))
        return self._root / "survey" / time.strftime("%Y%m%d", time.localtime(now))

    def __call__(self, kind) -> str | None:
        kind = str(kind or "picture")
        quick = kind.startswith("look_")                                                         # throwaway look pictures: no camera warm-up, no retake, a short wait for stillness (a full picture took 15 s)
        prep = False if quick else (self._prep_every_s <= 0 or kind.startswith("name:") or self._last_prep is None or self._clock() - self._last_prep >= self._prep_every_s)
        still = None
        if self._wait_still is not None:
            try:
                still = self._wait_still(2.0) if quick else self._wait_still()                                                       # the body must have stopped swaying before the shutter (camera shake)
            except Exception:  # noqa: BLE001
                log.debug("wait for stillness failed", exc_info=True)
        snap = self._take(prep)
        if prep and snap is not None:
            self._last_prep = self._clock()
        retaken = False
        if snap is not None and not quick and _badly_exposed(snap.jpeg):                                       # too dark or too bright: warm the camera up again and take it once more, keep the better one
            again = self._take(True)
            retaken = True
            if again is not None and _exposure_cost(again.jpeg) < _exposure_cost(snap.jpeg):
                snap = again
        if snap is None:
            log.warning("no picture for %s (the camera did not answer)", kind)
            if self._on_failure:
                try:
                    self._on_failure(f"no picture for {kind}")
                except Exception:  # noqa: BLE001
                    pass
            return None
        if not _decodes(snap.jpeg):
            self.truncated = getattr(self, "truncated", 0) + 1
            log.warning("picture not kept: the JPEG is cut off or damaged (%s)", kind)         # 6 of 89 pictures from 10-07..10-09 were cut off
            return None
        now = self._clock()
        folder = self.folder_for(kind, now)
        folder.mkdir(parents=True, exist_ok=True)
        pose = "named" if kind.startswith("name:") else kind
        prefix = slug(kind[5:]) if kind.startswith("name:") else pose
        if self._is_duplicate(folder, prefix, snap.jpeg, self._named_distance if kind.startswith("name:") else self._survey_distance):
            self.duplicates += 1
            log.info("picture not kept: a near-duplicate of one already saved (%s)", kind)
            self._survey_stop(kind, None, {}, snap.jpeg)
            return None
        base = prefix + time.strftime("_%H%M%S", time.localtime(now)) + f"_{int((now % 1) * 1000):03d}"
        path = folder / (base + ".jpg")
        path.write_bytes(snap.jpeg)
        meta = {"still": still, "retaken": retaken, "file": path.name, "kind": kind, "pose": pose, "name": kind[5:] if kind.startswith("name:") else None,
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
        self._survey_stop(kind, str(path), meta, snap.jpeg)
        if kind.startswith("look_"):
            self._trim_looks(folder.parent)
            return str(path)                                             # look-only pictures are never offered to the object gallery
        if self._on_saved and kind.startswith("name:"):                 # only a picture named by voice feeds the object gallery; survey pictures wait for the filter, your label and a promotion (user, 2026-10-10)
            try:
                self._on_saved(str(path))
            except Exception:  # noqa: BLE001
                log.debug("on_saved hook failed", exc_info=True)
        return str(path)

    def _survey_stop(self, kind: str, path, meta: dict, jpeg: bytes) -> None:
        if self._on_survey_stop is not None and kind == "after_bow":
            try:
                self._on_survey_stop(path, meta, jpeg)
            except Exception:  # noqa: BLE001 -- a place record never stops a picture
                log.debug("on_survey_stop hook failed", exc_info=True)

    def _trim_looks(self, looks_root: Path, keep: int = 30) -> None:
        """Only the newest `keep` look pictures stay (user, 2026-10-10: throwaway pictures just for looking)."""
        try:
            jpgs = sorted(looks_root.glob("*/*.jpg"), key=lambda f: f.stat().st_mtime)
            for old in jpgs[:-keep]:
                old.unlink(missing_ok=True)
                old.with_suffix(".json").unlink(missing_ok=True)
        except OSError:
            pass

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
