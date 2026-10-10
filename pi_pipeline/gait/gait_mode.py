"""The gait the user has switched G2 to, shared by every part of the Pi (user, 2026-10-09: "make sure I can switch to a different gait at any time, exploration mode or other").

One small state file (`~/.local/share/g2/gait_mode.json`) is the single source of truth, so the voice service, an exploration session and a walk loop started by either, which are
separate processes, always agree. A voice command ("hi step", "walk normally") from ANY of them sets it; the walk loop reads `current()` every tick and, for a policy that supports the
mode, blends its base gait over `BLEND_S` seconds so a switch in the middle of a walk is smooth.

Gaits are a table, so more can be added later (a crawl, a trot) with a name, spoken phrases and a base reference. A policy declares what it was trained for in its `.onnx.json` sidecar
(`"modes": ["normal", "hi_step"]`); a policy without that key (V4, V5) supports only `normal`, and asking for another gait is refused out loud and changes nothing: switching the base
under a policy that never learned it was measured to be unstable (the unlearned high-step base falls 0.37 against 0.22 and sways three times as much).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

STATE_PATH = os.path.expanduser(os.environ.get("G2_GAIT_MODE_FILE", "~/.local/share/g2/gait_mode.json"))
BLEND_S = 1.3            # about one gait cycle at 0.1 m/s


@dataclass(frozen=True)
class Gait:
    name: str
    phrases: tuple          # spoken forms, normalised (lower case, no punctuation); a command may carry up to two extra words
    echo_on: str            # what G2 says when it is switched on
    base_ref: str           # <base_ref>_ref.npy: the scripted base the learned correction sits on (pi_pipeline/gait/, reference_gait/ in the training tree)
    scripted: bool = False  # can be played as a plain scripted walk (no learned correction) by a policy that does not know the gait: slow and experimental


GAITS = {
    "normal": Gait("normal", ("walk normally", "walk normal", "normal walk", "normal gait", "walk like normal", "walk mode", "walk mode on", "normal mode", "step mode off", "hi step off", "high step off",
                                "switch to normal", "switch to normal walk", "switch to normal walking", "switch to walk mode", "switch to normal mode"),
                   "Walking normally.", "wkf"),
    "hi_step": Gait("hi_step", ("hi step", "high step", "hi steps", "high steps", "hi step mode", "high step mode", "step mode", "step mode on", "hi step on", "high step on",
                                "highstep", "highstep mode", "i step", "eye step", "die step", "hi stepp",      # the last four: what the recognizer actually heard on G2 (2026-10-10: "i step", "switch die step")
                                 "switch to high step", "switch to hi step", "switch to highstep", "switch to high steps", "switch to high step mode", "switch to hi step mode", "switch to step mode"),
                    "Hi step on.", "hsF", scripted=True),
}
DEFAULT = "normal"
_PUNCT = re.compile(r"[^\w\s]")


def _norm(text: str) -> str:
    return " ".join(_PUNCT.sub(" ", (text or "").lower().replace("'", "")).split())


def parse_gait_command(text: str) -> str | None:
    """The gait a short spoken command asks for, or None. Off-phrases are checked first ("hi step off" must not turn it on)."""
    n = _norm(text)
    if not n or len(n.split()) > 6:
        return None
    for name in ("normal", "hi_step"):
        for p in sorted(GAITS[name].phrases, key=len, reverse=True):
            if n == p or (n.startswith(p + " ") and len(n.split()) - len(p.split()) <= 2) or (n.endswith(" " + p) and len(n.split()) - len(p.split()) <= 2):
                return name
    return None


def modes_of(sidecar_path: str | None) -> tuple:
    """The gaits a policy was trained for, from its `.onnx.json` sidecar; a policy without the key supports only the normal gait."""
    try:
        d = json.loads(Path(str(sidecar_path)).read_text())
        modes = tuple(m for m in d.get("modes", ()) if m in GAITS)
        return modes or (DEFAULT,)
    except (OSError, ValueError):
        return (DEFAULT,)


def supports(policy_onnx: str | None, gait: str) -> bool:
    return gait in modes_of(f"{policy_onnx}.json" if policy_onnx else None)


def _read(path: str) -> dict:
    try:
        d = json.loads(Path(path).read_text())
        return d if d.get("mode") in GAITS else {}
    except (OSError, ValueError):
        return {}


def current(path: str | None = None) -> str:
    return _read(path or STATE_PATH).get("mode", DEFAULT)


def blend(path: str | None = None, now: float | None = None) -> tuple[str, str, float]:
    """(from_gait, to_gait, alpha): alpha runs 0 -> 1 over BLEND_S after a switch, so the base is a mix of the old and new gait until then."""
    d = _read(path or STATE_PATH)
    if not d:
        return DEFAULT, DEFAULT, 1.0
    now = time.time() if now is None else now
    a = min(1.0, max(0.0, (now - float(d.get("since", 0.0))) / BLEND_S))
    return d.get("from", d["mode"]), d["mode"], a


def set_mode(gait: str, path: str | None = None, now: float | None = None) -> str:
    """Switch to `gait` (no support check: the caller checks the policy). Returns the gait. Never raises on a write error: the switch then simply does not stick."""
    if gait not in GAITS:
        raise ValueError(f"unknown gait {gait!r}")
    p = path or STATE_PATH
    old = _read(p).get("mode", DEFAULT)
    if old == gait:
        return gait
    try:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        tmp = p + ".tmp"
        Path(tmp).write_text(json.dumps({"mode": gait, "from": old, "since": time.time() if now is None else now}))
        os.replace(tmp, p)
    except OSError:
        pass
    return gait


def request(text: str, policy_onnx: str | None = None, path: str | None = None) -> tuple[str | None, str]:
    """For the voice loop and the exploration listener: (gait or None, the sentence to say). Switches only when the policy supports the gait."""
    gait = parse_gait_command(text)
    if gait is None:
        return None, ""
    label = "hi step" if gait == "hi_step" else gait.replace("_", " ")
    if not supports(policy_onnx, gait):
        if GAITS[gait].scripted:                          # a scripted walk without the learned correction: allowed, said out loud, experimental
            set_mode(gait, path)
            return gait, f"{GAITS[gait].echo_on} It is a scripted walk without my learned correction, so it is slow and experimental."
        return None, f"My walking policy doesn't have {label} yet, so I'm staying as I am."
    set_mode(gait, path)
    return gait, GAITS[gait].echo_on
