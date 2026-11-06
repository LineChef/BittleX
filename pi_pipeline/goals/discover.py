"""The "Identify new objects" goal (user, 2026-11-06): G2 roams, finds things he does not recognise yet, and takes pictures of them so they can become recognition data.

An attempt is one roam (an exploration session, `explore_session.run_inprocess`) with the picture-stop settings of the knobs. Exploration already does the finding: a background look
asks the interest scorer whether an unknown object is in view (not a person, not a wall's base), the survey takes the picture routine, and the gallery files the pictures as an unnamed
candidate (`behavior/interest_watch.py`, `vision/object_gallery.py`). This goal adds the measuring and the learning: what an attempt produced is read back from the gallery file and the new
pictures' sidecars, scored, and the judge tunes how often he looks and when he gives up being picky, per floor and hardware, like the ball goal.

  new_object     a candidate that was not in the gallery before, with MIN_PICTURES or more usable pictures taken during the roam        success
  few_pictures   a new candidate, but fewer usable pictures than that                                                                   partial
  nothing_new    pictures were taken, but everything in them was already known (no new candidate)                                         miss
  never_found    no picture stop at all                                                                                                 miss
  fell           he fell                                                                                                                failed
  stopped        the user stopped it                                                                                                    not counted

A usable picture: a survey picture (not a throwaway look), no person detected in it, sensibly exposed. The pictures are filed under the room he was told he is in (memory/places.py) and
appear in the Pictures tab of g2pics unnamed: you name them there, or he asks "what am I looking at?". Nothing here calls the API.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .approach import AttemptContext, AttemptResult, Outcome, register
from .spec import Knob

MIN_PICTURES = 3

# name -> (kind, lo, hi, step, default, control, label, unit)
SPEC = {
    "roam_s": ("int", 60, 300, 30, 180, "free", "roaming for", "s an attempt"),
    "peek_every_s": ("float", 4.0, 20.0, 2.0, 8.0, "free", "looking for something new every", "s"),
    "fallback_s": ("int", 60, 600, 60, 300, "free", "taking a picture anyway after", "s without one"),
    "relax_s": ("int", 20, 180, 20, 60, "free", "dropping my pickiness after", "s with no picture"),
}
DIAGNOSIS = {
    "never_found": [("peek_every_s", -1), ("relax_s", -1), ("fallback_s", -1), ("roam_s", +1)],
    "nothing_new": [("roam_s", +1), ("peek_every_s", -1)],
    "few_pictures": [("relax_s", -1), ("fallback_s", -1)],
}
STAGE_OF = {k: "find" for k in SPEC}
ENV = {"peek_every_s": "G2_INTEREST_EVERY_S", "fallback_s": "G2_INTEREST_FALLBACK_S", "relax_s": "G2_SURVEY_RELAX_S"}
PEOPLE = frozenset({"person", "face", "human"})


def pictures_root() -> Path:
    try:
        from ..vision.exploration_pictures import DEFAULT_ROOT
    except Exception:  # noqa: BLE001
        DEFAULT_ROOT = "~/.local/share/g2/explore_pictures"
    return Path(os.path.expanduser(os.environ.get("G2_EXPLORE_PICTURES_DIR", DEFAULT_ROOT)))


def gallery_path() -> Path:
    try:
        from ..config import settings
        d = settings.object_gallery_dir
    except Exception:  # noqa: BLE001
        d = "~/.local/share/g2/object_gallery"
    return Path(os.path.expanduser(d)) / "gallery.json"


def gallery_state(path: Path | None = None) -> dict:
    """{entry id: {"named": bool, "samples": n}} from the gallery file; {} when there is none."""
    try:
        d = json.loads((path or gallery_path()).read_text())
        return {eid: {"named": bool(e.get("name")), "samples": int(e.get("sample_count", 0))} for eid, e in (d.get("entries") or {}).items()}
    except (OSError, ValueError):
        return {}


def pictures_since(t0: float, root: Path | None = None) -> list[dict]:
    """The sidecars of survey and named pictures saved at or after wall-clock `t0`: [{"file", "usable", "people", "kind"}]."""
    root = root or pictures_root()
    out = []
    for top in ("survey", "named"):
        for js in (root / top).rglob("*.json") if (root / top).is_dir() else ():
            try:
                if js.stat().st_mtime < t0:
                    continue
                meta = json.loads(js.read_text())
            except (OSError, ValueError):
                continue
            kind = str(meta.get("kind") or "")
            if kind.startswith("look_"):
                continue
            labels = {str(d.get("label", "")).lower() for d in (meta.get("detections") or [])}
            ex = meta.get("exposure") or {}
            mean, clip = ex.get("mean"), ex.get("clip_high")
            ok = (mean is None or 25.0 <= mean <= 235.0) and (clip is None or clip <= 0.30)
            people = bool(labels & PEOPLE)
            out.append({"file": js.with_suffix(".jpg").name, "kind": kind, "people": people, "usable": ok and not people, "place": meta.get("place")})
    return out


def judge_roam(ended: str, before: dict, after: dict, pics: list[dict]) -> dict:
    """What a roam produced, in numbers: new unnamed candidates, usable pictures, and how it ended."""
    new = [e for e in after if e not in before]
    grown = [e for e in after if e in before and not after[e]["named"] and after[e]["samples"] > before[e]["samples"]]
    usable = [p for p in pics if p["usable"]]
    return {"ended": ended, "new_candidates": len(new), "grown_candidates": len(grown), "pictures": len(pics), "usable": len(usable), "people": sum(1 for p in pics if p["people"]),
            "places": sorted({p["place"] for p in pics if p.get("place")})}


@register("discover_objects")
class DiscoverObjects:
    name = "discover_objects"
    diagnosis = DIAGNOSIS
    stage_of = STAGE_OF

    def __init__(self, *, shared=None, run=None):
        self._shared = shared
        self._run = run                                           # tests: (settings, ctx) -> how the roam ended
        self.last_pack_pct = None

    def knobs(self) -> list[Knob]:
        return [Knob(n, kind, lo=lo, hi=hi, step=step, control=ctl, label=label, unit=unit) for n, (kind, lo, hi, step, _d, ctl, label, unit) in SPEC.items()]

    def base_settings(self) -> dict:
        return {n: v[4] for n, v in SPEC.items()}

    def conditions(self) -> dict:
        return {}

    def open(self) -> None:
        pass                                                      # the exploration session opens and closes what it needs; in the voice service it borrows the service's parts

    def close(self) -> None:
        pass

    def battery_ok(self, min_pct: int) -> tuple[bool, str]:
        link = getattr(self._shared, "link", None)
        if link is None:
            return True, "battery not checked (no link)"
        from ..power import battery
        ok, pct, volts = battery.motion_gate(link)
        self.last_pack_pct = pct
        if pct is None:
            return ok, "battery unreadable: continuing" if ok else "battery unreadable"
        if not ok or pct < min_pct:
            return False, f"battery {pct}% ({volts:.2f} V), below {min_pct}%"
        return True, f"battery {pct}% ({volts:.2f} V)"

    def run_attempt(self, settings: dict, ctx: AttemptContext) -> AttemptResult:
        t_wall, t0 = time.time(), time.monotonic()
        before = gallery_state()
        roam_s = int(settings.get("roam_s", SPEC["roam_s"][4]))
        saved = {var: os.environ.get(var) for var in ENV.values()}
        for k, var in ENV.items():
            if k in settings:
                os.environ[var] = str(settings[k])
        done = threading.Event()

        def watch_stop():                                          # the user's stop ends the roam through the exploration session's own command file
            while not done.wait(0.5):
                if ctx.stop():
                    try:
                        from ..explore_session import CMD_FILE
                        Path(CMD_FILE).write_text("stop\n")
                    except Exception:  # noqa: BLE001
                        pass
                    return
        threading.Thread(target=watch_stop, name="discover-stop", daemon=True).start()
        try:
            if self._run is not None:
                ended = self._run(settings, ctx)
            elif self._shared is not None:
                from ..explore_session import run_inprocess
                ended = run_inprocess(self._shared, roam_s)
            else:
                from ..explore_session import parse_args, run_session
                ended = run_session(parse_args(["--arm-on-start", "--exit-when-roam-ends", "--roam-s", str(roam_s)]))
        finally:
            done.set()
            for var, old in saved.items():
                if old is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = old
            if self._shared is not None:
                self._shared.exploring.set()                       # the goal session keeps the service's guards aside between attempts
        extra = judge_roam(str(ended), before, gallery_state(), pictures_since(t_wall - 1.0))
        extra["roam_s"] = roam_s
        ctx.say(f"roam over ({ended}): {extra['pictures']} pictures, {extra['usable']} usable, {extra['new_candidates']} new candidate(s)")
        return AttemptResult(str(ended), round(time.monotonic() - t0, 1), [], extra)

    def score(self, result: AttemptResult, settings: dict) -> Outcome:
        x = result.extra
        n = {k: x.get(k) for k in ("new_candidates", "grown_candidates", "pictures", "usable", "people")}
        ended = (result.ended or "").lower()
        if "fell" in ended:
            return Outcome("fell", 0.0, False, "I fell while looking for new objects", n, stages={"find": 0.0})
        if any(w in ended for w in ("voice command", "stopped", "stop")):
            return Outcome("stopped", None, False, "I was stopped while looking for new objects", n)
        if x.get("new_candidates", 0) >= 1 and x.get("usable", 0) >= MIN_PICTURES:
            return Outcome("new_object", 1.0, True, f"I found something new and took {x['usable']} usable pictures of it", n, stages={"find": 1.0})
        if x.get("new_candidates", 0) >= 1:
            return Outcome("few_pictures", 0.5, False, f"I found something new but only {x.get('usable', 0)} of its pictures were usable (I need {MIN_PICTURES})", n, stages={"find": 0.5})
        if x.get("pictures", 0) > 0:
            return Outcome("nothing_new", 0.2, False, f"I took {x['pictures']} pictures but everything in them was already known", n, stages={"find": 0.2})
        return Outcome("never_found", 0.0, False, "I did not find anything worth a picture", n, stages={"find": 0.0})
