#!/usr/bin/env python3
"""Curate the pictures G2 saved while exploring into a clean, labelled set (Phase 2 of docs/vision/exploration-object-learning-plan.md).

Input is the folder `g2pics pull` copies to the Mac (`~/g2_pictures/explore`): `survey/<date>/*.jpg` from the survey stops and
`named/<name>/*.jpg` from "this is a mug", each with a `.json` sidecar (pose, name, time, what the on-camera detector saw). It:

  1. scores every picture: brightness, contrast, sharpness, clipped highlights / shadows;
  2. sets aside every picture with a person in it (user, 2026-10-07; not curated, not copied, listed in the manifest only), in layers: the camera's own detector, an outside person model (tools/person_filter.py, until the on-camera
     model is trained), anything taken within 2 minutes of such a picture (legs and backs the models miss), and pictures marked "Person" by hand on the g2pics page (`people.json`);
  3. rejects survey pictures that are too dark, blown out, blurry, flat or truncated (the camera module cut the JPEG short, so the lower part is gray); named pictures are never rejected for quality, only flagged "weak";
  4. removes near-duplicates (256-bit average hash; 12 bits within one survey pose, 3 bits within one name), keeping the best-scoring picture of each cluster;
  5. writes `keep/` (same folder layout), `rejects/<reason>/`, a contact sheet per group (green = kept, orange = weak; the camera's own boxes are drawn),
     `manifest.json` (every picture, its scores and its fate) and `summary.txt` (counts per pose and per name, with hints).

Input is never modified. Deps: Pillow, numpy (dev machine).

    python tools/curate_exploration.py [IN_DIR] [OUT_DIR] [options]       defaults: ~/g2_pictures/explore  training_data/exploration/<date_time>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from curate_captures import ahash, brightness_contrast, hamming, sharpness  # noqa: E402  -- the capture tools' own quality functions

ROOT = os.path.dirname(HERE)
DEFAULT_IN = os.path.expanduser("~/g2_pictures/explore")


@dataclass
class Config:
    min_brightness: float = 22.0
    max_brightness: float = 245.0
    max_clip_high: float = 0.30        # share of pixels at or near white above which a picture counts as blown out
    min_sharpness: float = 8.0         # variance of the Laplacian
    min_contrast: float = 12.0
    survey_dup_bits: int = 12          # same distances the Pi uses when it saves
    named_dup_bits: int = 3
    target_brightness: float = 110.0
    non_person_labels: tuple = ("dog", "cat")     # detections with these labels do not make a picture a "people" picture
    person_min_score: float = 0.40
    person_detector: object = None     # callable(PIL image) -> best person score 0..1 (tools/person_filter.PersonDetector.best_score); None = the camera's own detections only
    person_threshold: float = 0.25     # eager on purpose: leaving a picture out costs little, keeping a person in the object library costs more
    person_window_s: float = 120.0     # pictures taken this close in time to a picture with a person are set aside too (legs and backs the models miss)
    named_min_keep: int = 5            # fewer kept pictures than this for a name gets a hint
    thumb: int = 150
    cols: int = 6


@dataclass
class Pic:
    path: str
    rel: str                           # path inside the input folder
    group: str                         # "survey/20261007" or "named/red-mug"
    pose: str = ""
    name: str | None = None
    taken: str = ""
    dets: list = field(default_factory=list)
    width: int = 0
    height: int = 0
    bright: float = 0.0
    contrast: float = 0.0
    sharp: float = 0.0
    clip_high: float = 0.0
    clip_low: float = 0.0
    hash: int = 0
    quality: float = 0.0
    status: str = "kept"               # kept | weak | rejected | duplicate | people
    reason: str = ""
    duplicate_of: str | None = None
    person_why: str = ""               # why this picture is treated as having a person in it ("" = none)
    person_score: float = 0.0
    cut_off: bool = False              # the JPEG has no end marker: the camera module cut it short (the rest decodes as flat gray)

    @property
    def named(self) -> bool:
        return self.group.startswith("named/")

    @property
    def key(self) -> str:
        """What a near-duplicate is judged within: one name, or one survey pose."""
        return self.group if self.named else "survey/" + (self.pose or "picture")


def _load(in_dir: str) -> list[Pic]:
    pics: list[Pic] = []
    for top in ("survey", "named"):
        base = os.path.join(in_dir, top)
        for dirpath, _dirs, files in sorted(os.walk(base)):
            for fn in sorted(files):
                if not fn.lower().endswith(".jpg"):
                    continue
                path = os.path.join(dirpath, fn)
                p = Pic(path=path, rel=os.path.relpath(path, in_dir), group=os.path.relpath(dirpath, in_dir))
                side = os.path.splitext(path)[0] + ".json"
                try:
                    d = json.load(open(side))
                    p.pose, p.name, p.taken = str(d.get("pose") or ""), d.get("name"), str(d.get("time") or "")
                    p.dets = list(d.get("detections") or [])
                except (OSError, ValueError):
                    pass
                if not p.pose:                                    # no sidecar: the file name starts with the pose (survey) or name
                    p.pose = "named" if p.named else fn.split("_")[0]
                pics.append(p)
    return pics


def _is_cut_off(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read().rstrip(b"\x00")[-2:] != b"\xff\xd9"
    except OSError:
        return False


def _measure(p: Pic) -> bool:
    p.cut_off = _is_cut_off(p.path)
    try:
        ImageFile.LOAD_TRUNCATED_IMAGES = True              # a cut-off picture still decodes (the missing part is gray); it is flagged, not lost
        im = Image.open(p.path)
        im.load()
    except Exception:  # noqa: BLE001 -- an unreadable file is a reject, not a crash
        return False
    p.width, p.height = im.size
    p.bright, p.contrast = brightness_contrast(im)
    p.sharp = sharpness(im)
    g = np.asarray(im.convert("L"))
    p.clip_high, p.clip_low = float((g >= 250).mean()), float((g <= 5).mean())
    p.hash = ahash(im, 16)
    return True


def _quality(p: Pic, c: Config) -> float:
    s_sharp = min(1.0, p.sharp / 60.0)
    s_bright = 1.0 - min(1.0, abs(p.bright - c.target_brightness) / c.target_brightness)
    s_contrast = min(1.0, p.contrast / 45.0)
    penalty = 0.30 * min(1.0, max(0.0, p.clip_high - 0.05) / 0.25)
    return round(0.45 * s_sharp + 0.30 * s_bright + 0.25 * s_contrast - penalty, 4)


def _quality_problem(p: Pic, c: Config) -> str:
    if p.bright < c.min_brightness:
        return "too_dark"
    if p.bright > c.max_brightness or p.clip_high > c.max_clip_high:
        return "blown_out"
    if p.sharp < c.min_sharpness:
        return "blurry"
    if p.contrast < c.min_contrast:
        return "low_contrast"
    return ""


def _has_person(p: Pic, c: Config) -> bool:
    return any(float(d.get("score", 0.0)) >= c.person_min_score and str(d.get("label", "")).lower() not in c.non_person_labels for d in p.dets)


def _read_marks(in_dir: str) -> set:
    """Pictures a person marked as containing a person, by hand (the "Person" button on the g2pics page): `people.json`, a list of paths inside the pictures folder."""
    try:
        return set(json.load(open(os.path.join(in_dir, "people.json"))))
    except (OSError, ValueError):
        return set()


def _taken_epoch(p: Pic) -> float | None:
    try:
        return time.mktime(time.strptime(p.taken, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return None


def _person_reason(p: Pic, c: Config, marks: set) -> str:
    """Layer 1: marked by hand, the camera's own detector, the outside person model."""
    if p.rel in marks:
        return "marked as a person by hand"
    if _has_person(p, c):
        return "on-camera detector saw a person or face"
    if c.person_detector is not None:
        try:
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            p.person_score = float(c.person_detector(Image.open(p.path)))
        except Exception:  # noqa: BLE001 -- a detector failure must not stop the curation
            return ""
        if p.person_score >= c.person_threshold:
            return f"person model found a person ({p.person_score:.2f})"
    return ""


def _spread_person_flags(pics: list[Pic], c: Config) -> None:
    """Layer 2: a picture taken within `person_window_s` of one with a person is set aside too, which catches the legs and backs that neither model sees."""
    flagged = [(t, p) for p in pics if p.person_why and (t := _taken_epoch(p)) is not None]
    if not flagged:
        return
    for p in pics:
        if p.person_why:
            continue
        t = _taken_epoch(p)
        if t is None:
            continue
        near = min(flagged, key=lambda tp: abs(tp[0] - t))
        if abs(near[0] - t) <= c.person_window_s:
            p.person_why = f"taken within {c.person_window_s:.0f} s of a picture with a person"


def curate(in_dir: str, out_dir: str, c: Config | None = None, *, write: bool = True) -> dict:
    """Run the pipeline; returns the manifest dict. `write=False` computes it without copying anything."""
    c = c or Config()
    pics = _load(in_dir)
    live: list[Pic] = []
    marks = _read_marks(in_dir)
    measured: list[Pic] = []
    for p in pics:
        if not _measure(p):
            p.status, p.reason = "rejected", "unreadable"
            continue
        p.quality = _quality(p, c)
        if p.cut_off:
            p.quality = round(p.quality * 0.5, 4)
        p.person_why = _person_reason(p, c, marks)
        measured.append(p)
    _spread_person_flags(measured, c)
    for p in measured:
        if p.person_why:
            p.status, p.reason = "people", p.person_why
            continue
        problem = "truncated" if p.cut_off else _quality_problem(p, c)
        if problem and p.named:
            p.status, p.reason = "weak", problem                  # named pictures are kept; the flag tells you which to retake
        elif problem:
            p.status, p.reason = "rejected", problem
        live.append(p)
    kept_by_key: dict[str, list[Pic]] = {}
    for p in sorted([x for x in live if x.status != "rejected"], key=lambda x: (-x.quality, x.taken, x.rel)):     # best first
        limit = c.named_dup_bits if p.named else c.survey_dup_bits
        twin = next((k for k in kept_by_key.setdefault(p.key, []) if hamming(k.hash, p.hash) <= limit), None)
        if twin is None:
            kept_by_key[p.key].append(p)
        else:
            p.status, p.reason, p.duplicate_of = "duplicate", "near-duplicate of a better picture", twin.rel
    manifest = _manifest(pics, in_dir, out_dir, c)
    if write:
        _write(pics, in_dir, out_dir, c, manifest)
    return manifest


def _manifest(pics: list[Pic], in_dir: str, out_dir: str, c: Config) -> dict:
    rows = [dict(file=p.rel, group=p.group, pose=p.pose, name=p.name, time=p.taken, status=p.status, reason=p.reason, duplicate_of=p.duplicate_of,
                 brightness=round(p.bright, 1), contrast=round(p.contrast, 1), sharpness=round(p.sharp, 1), clip_high=round(p.clip_high, 3),
                 clip_low=round(p.clip_low, 3), quality=p.quality, detections=p.dets) for p in sorted(pics, key=lambda x: x.rel)]
    return {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "input": in_dir, "output": out_dir, "pictures": rows, "summary": _summary(pics, c)}


def _summary(pics: list[Pic], c: Config) -> dict:
    out = {"total": len(pics), "by_status": {}, "by_pose": {}, "by_name": {}, "hints": []}
    for p in pics:
        out["by_status"][p.status] = out["by_status"].get(p.status, 0) + 1
        if p.named:
            n = out["by_name"].setdefault(p.name or p.group.split("/", 1)[1], {"kept": 0, "weak": 0, "duplicate": 0, "people": 0, "rejected": 0})
            n[p.status] += 1
        else:
            s = out["by_pose"].setdefault(p.pose, {"kept": 0, "rejected": 0, "duplicate": 0, "people": 0, "reasons": {}, "bright": []})
            s[p.status] += 1
            s["bright"].append(p.bright)
            if p.status == "rejected":
                s["reasons"][p.reason] = s["reasons"].get(p.reason, 0) + 1
    for pose, s in out["by_pose"].items():
        n = s["kept"] + s["rejected"] + s["duplicate"] + s["people"]
        mean_b = float(np.mean(s["bright"])) if s["bright"] else 0.0
        s["mean_brightness"] = round(mean_b, 1)
        del s["bright"]
        if n >= 4 and s["rejected"] / n > 0.5:
            top = max(s["reasons"], key=s["reasons"].get) if s["reasons"] else "quality"
            out["hints"].append(f"'{pose}' pictures: {s['rejected']} of {n} rejected, mostly {top}: this angle may not be giving usable views (for example mostly ceiling or floor).")
        if n >= 4 and s["duplicate"] / n > 0.6:
            out["hints"].append(f"'{pose}' pictures: {s['duplicate']} of {n} are near-duplicates: the view barely changes between survey stops.")
        if s["people"]:
            out["hints"].append(f"'{pose}': {s['people']} picture(s) with a person or face were set aside (not copied).")
    for name, n in out["by_name"].items():
        have = n["kept"] + n["weak"]
        if have < c.named_min_keep:
            out["hints"].append(f"'{name}': only {have} usable picture(s); name it again from a few other angles and distances (aim for {c.named_min_keep}+).")
        if n["weak"]:
            out["hints"].append(f"'{name}': {n['weak']} picture(s) flagged weak (too dark, blown out, blurry or flat); retake if recognition struggles.")
    return out


def _safe(rel: str) -> str:
    return rel.replace(os.sep, "__")


def _write(pics: list[Pic], in_dir: str, out_dir: str, c: Config, manifest: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for p in pics:
        if p.status in ("kept", "weak"):
            dest = os.path.join(out_dir, "keep", p.rel)
        elif p.status in ("rejected", "duplicate"):
            dest = os.path.join(out_dir, "rejects", p.reason.split(" ")[0] if p.status == "rejected" else "duplicate", _safe(p.rel))
        else:
            continue                                   # people: listed in the manifest, never copied
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(p.path, dest)
        side = os.path.splitext(p.path)[0] + ".json"
        if os.path.isfile(side):
            shutil.copy2(side, os.path.splitext(dest)[0] + ".json")
    groups: dict[str, list[Pic]] = {}
    for p in pics:
        if p.status in ("kept", "weak"):
            groups.setdefault(p.group, []).append(p)
    for g, items in groups.items():
        _contact_sheet(items, os.path.join(out_dir, "contact", _safe(g) + ".jpg"), g, c)
    rej = [p for p in pics if p.status == "rejected"][:60]
    if rej:
        _contact_sheet(rej, os.path.join(out_dir, "contact", "rejects.jpg"), "rejects", c)
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    with open(os.path.join(out_dir, "summary.txt"), "w") as f:
        f.write(summary_text(manifest))


def _contact_sheet(items: list[Pic], path: str, title: str, c: Config) -> None:
    t, cols = c.thumb, max(1, min(c.cols, len(items)))
    rows = max(1, -(-len(items) // cols))
    sheet = Image.new("RGB", (max(cols * t, 260), rows * (t + 16) + 18), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    d.text((4, 3), f"{title}  ({len(items)})", fill=(230, 230, 230))
    for i, p in enumerate(sorted(items, key=lambda x: x.taken or x.rel)):
        x, y = (i % cols) * t, 18 + (i // cols) * (t + 16)
        try:
            im = Image.open(p.path).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        sheet.paste(im.resize((t, t)), (x, y))
        for det in p.dets:                                   # the camera's own boxes, as it saw them (normalised centre and size)
            cx, cy, w, h = (float(det.get(k, 0.0)) for k in ("cx", "cy", "w", "h"))
            d.rectangle([x + (cx - w / 2) * t, y + (cy - h / 2) * t, x + (cx + w / 2) * t, y + (cy + h / 2) * t], outline=(255, 70, 70))
        edge = (230, 150, 40) if p.status in ("weak", "rejected") else (60, 200, 90)
        d.rectangle([x, y, x + t - 1, y + t - 1], outline=edge)
        label = f"{p.reason or p.pose} {p.quality:.2f}" if p.status in ("weak", "rejected") else f"{p.pose} {p.quality:.2f}"
        d.text((x + 2, y + t + 2), label[:26], fill=(200, 200, 200))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sheet.save(path, quality=88)


def summary_text(manifest: dict) -> str:
    s = manifest["summary"]
    lines = [f"Exploration pictures: {s['total']} total", "  " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_status"].items()))]
    if s["by_pose"]:
        lines.append("Survey pictures by pose:")
        for pose, v in sorted(s["by_pose"].items()):
            reasons = ", ".join(f"{k} {n}" for k, n in sorted(v["reasons"].items()))
            lines.append(f"  {pose}: kept {v['kept']}, rejected {v['rejected']}" + (f" ({reasons})" if reasons else "")
                         + f", duplicates {v['duplicate']}, people {v['people']}, mean brightness {v['mean_brightness']}")
    if s["by_name"]:
        lines.append("Named objects:")
        for name, v in sorted(s["by_name"].items()):
            lines.append(f"  {name}: kept {v['kept']}, weak {v['weak']}, duplicates {v['duplicate']}, people {v['people']}")
    if s["hints"]:
        lines.append("Hints:")
        lines += [f"  - {h}" for h in s["hints"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("in_dir", nargs="?", default=DEFAULT_IN)
    ap.add_argument("out_dir", nargs="?", default=None)
    ap.add_argument("--min-brightness", type=float, default=Config.min_brightness)
    ap.add_argument("--min-sharpness", type=float, default=Config.min_sharpness)
    ap.add_argument("--min-contrast", type=float, default=Config.min_contrast)
    ap.add_argument("--survey-dup-bits", type=int, default=Config.survey_dup_bits)
    ap.add_argument("--named-dup-bits", type=int, default=Config.named_dup_bits)
    ap.add_argument("--person-model", default=os.path.expanduser("~/g2_data/models/yolox_s.onnx"), help="outside person model (ONNX) used until the on-camera model is trained; skipped if the file is missing")
    ap.add_argument("--no-person-model", action="store_true")
    ap.add_argument("--person-window-s", type=float, default=Config.person_window_s)
    ap.add_argument("--non-person-labels", default=",".join(Config.non_person_labels),
                    help="detection labels that do not make a picture a people picture (comma separated; any other detection does)")
    a = ap.parse_args(argv)
    in_dir = os.path.expanduser(a.in_dir)
    if not os.path.isdir(in_dir):
        print(f"no such folder: {in_dir} (run `g2pics pull` first)")
        return 1
    out_dir = os.path.expanduser(a.out_dir) if a.out_dir else os.path.join(ROOT, "training_data", "exploration", time.strftime("%Y%m%d_%H%M"))
    c = Config(min_brightness=a.min_brightness, min_sharpness=a.min_sharpness, min_contrast=a.min_contrast, survey_dup_bits=a.survey_dup_bits,
               named_dup_bits=a.named_dup_bits, non_person_labels=tuple(x.strip().lower() for x in a.non_person_labels.split(",") if x.strip()))
    if not a.no_person_model:
        if os.path.isfile(os.path.expanduser(a.person_model)):
            try:
                from person_filter import PersonDetector
                c.person_detector = PersonDetector(os.path.expanduser(a.person_model), min_score=0.12).best_score
            except Exception as e:  # noqa: BLE001
                print(f"person model not usable ({e}); using the camera's detections and hand marks only")
        else:
            print(f"no person model at {a.person_model}; using the camera's detections and hand marks only")
    c.person_window_s = a.person_window_s
    m = curate(in_dir, out_dir, c)
    print(summary_text(m))
    print(f"written to {out_dir}  (keep/, rejects/, contact/, manifest.json, summary.txt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
