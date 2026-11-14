"""The gait the user has switched G2 to, shared by every part of the Pi (user, 2026-10-09: "make sure I can switch to a different gait at any time, exploration mode or other").

One small state file (`~/.local/share/g2/gait_mode.json`) is the single source of truth, so the voice service, an exploration session and a walk loop started by either, which are
separate processes, always agree. A voice command ("hi step", "walk normally") from ANY of them sets it; the walk loop reads `current()` every tick and, for a policy that supports the
mode, blends its base gait over `BLEND_S` seconds so a switch in the middle of a walk is smooth.

Gaits are a table, so more can be added later (a crawl, a trot) with a name, spoken phrases and a base reference. Any gait in the table can be switched to under any policy; nothing is refused.
A policy declares what it was trained for in its `.onnx.json` sidecar (`"modes": ["normal", "hi_step"]`): that picks HOW the gait is played, not whether. A policy that lists the gait plays it
with its learned correction on the gait's base; a policy that does not (V4, V5, V6: no `modes` key means `normal` only) plays the gait's scripted base through the open-loop player, with no
learned correction, and says so out loud ("slow and experimental"). The goal of a gait such as the high step is foot clearance, not stability, so a higher fall rate than the normal walk is expected.
(An earlier version refused the switch for a policy without the mode, citing a measurement of the crouching `hsF` under a normal-only policy; that measured the combination, not the
switch, and the switch itself always worked, so the refusal was removed 2026-10-12.)
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
    scripted_fallback: bool = True   # a policy without this mode plays the gait's scripted base; False: it walks its normal learned gait instead
    skill: str | None = None         # a gait that lives in the BiBoard firmware (no policy, no scripted base): the token the walker sends (carpet: Petoi's kcarpetF)


GAITS = {
    "normal": Gait("normal", ("walk normally", "walk normal", "normal walk", "normal gait", "walk like normal", "walk mode", "walk mode on", "normal mode", "step mode off", "hi step off", "high step off",
                                "switch to normal", "switch to normal walk", "switch to normal walking", "switch to walk mode", "switch to normal mode",
                                "switch to default gait", "switch to default", "switch to default walk", "default gait", "default walk", "default mode",   # user, 2026-10-20: "G2, switch to default gait"
                                "carpet mode off", "carpet off", "carpet walk off"),
                   "Walking normally.", "wkf"),
    "hi_step": Gait("hi_step", ("hi step", "high step", "hi steps", "high steps", "hi step mode", "high step mode", "step mode", "step mode on", "hi step on", "high step on",
                                "highstep", "highstep mode", "i step", "eye step", "die step", "hi stepp",      # the last four: what the recognizer actually heard on G2 (2026-10-10: "i step", "switch die step")
                                 "switch to high step", "switch to hi step", "switch to highstep", "switch to high steps", "switch to high step mode", "switch to hi step mode", "switch to step mode"),
                    "Hi step on.", "hsF"),
    # carpet (user, 2026-10-20: "G2, carpet mode"; user, 2026-10-21: "set petoi's carpet gait as the carpet policy"): Petoi's own firmware carpet gait (kcarpetF), so a walk in this
    # mode is the firmware skill, with no learned policy. (residual_policy.CARPET_POLICY, a carpet-only learned policy file, is no longer what carpet mode plays.)
    # Bare "carpet" is not a phrase: "we're on carpet" answers the floor question and must not switch the gait.
    "carpet": Gait("carpet", ("carpet mode", "carpet mode on", "carpet walk", "carpet gait", "carpet walking", "switch to carpet mode", "switch to carpet", "switch to carpet walk",
                              "switch to carpet gait", "walk on carpet mode"),
                   "Carpet mode on.", "wkf", scripted_fallback=False, skill="kcarpetF"),
}
DEFAULT = "normal"
_PUNCT = re.compile(r"[^\w\s]")


def _norm(text: str) -> str:
    return " ".join(_PUNCT.sub(" ", (text or "").lower().replace("'", "")).split())


def parse_gait_command(text: str) -> str | None:
    """The gait a short spoken command asks for, or None. Off-phrases are checked first ("hi step off" must not turn it on)."""
    n = _norm(text)
    n = " ".join({"switched": "switch", "switching": "switch", "changed": "change"}.get(w, w) for w in n.split()).replace(" to a ", " to ").replace(" to the ", " to ")      # the recognizer's "switched to a high step" (2026-10-10); an article elsewhere ("what is a high step") stays so it is not a command
    if not n or len(n.split()) > 6:
        return None
    for name in ("normal", "hi_step", "carpet"):
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
    if GAITS[gait].skill:                                 # a firmware gait: independent of the policy
        return True
    return gait in modes_of(f"{policy_onnx}.json" if policy_onnx else None)


def carpet_available() -> bool:
    try:
        from .residual_policy import carpet_policy_path
    except ImportError:                                   # imported as a plain script (run_gait.py puts gait/ on the path)
        from residual_policy import carpet_policy_path
    return carpet_policy_path() is not None


def _read(path: str) -> dict:
    try:
        d = json.loads(Path(path).read_text())
        return d if d.get("mode") in GAITS else {}
    except (OSError, ValueError):
        return {}


def _profile() -> dict:
    """The fitted attachment's profile in gait_profiles.json ({} when unreadable)."""
    try:
        from pi_pipeline.attachments import current as _att, load_profiles
        return load_profiles().get(_att()) or {}
    except Exception:  # noqa: BLE001
        return {}


def allowed_gaits() -> list:
    """The gaits this attachment may switch to: the profile's own `gaits` list (the arm: normal and hi_step), else every gait when `gait_switching` is on, else only the normal one."""
    g = _profile().get("gaits")
    if isinstance(g, list) and g:
        return [x for x in g if x in GAITS]
    return list(GAITS) if switching_allowed() else [DEFAULT]


def mode_policy(mode: str) -> str | None:
    """The learned policy a gait plays AS IT IS (no scripted base): the profile's `hi_step_policy` for the high step ("G2, switch to high step": the trained V7 policy for the arm, owner 2026-11-13;
    `G2_HIGHSTEP_POLICY` overrides), else None (the gait is played the way it always was)."""
    if mode != "hi_step":
        return None
    return os.environ.get("G2_HIGHSTEP_POLICY", "").strip() or _profile().get("hi_step_policy") or None


def floor_policy(floor: str | None) -> str | None:
    """The learned policy the profile names for a floor (the arm: tile -> V7), else None (the default walk). `G2_FLOOR_POLICIES` (`tile=Release_CandidateV7_ppo.onnx,...`) overrides."""
    fl = (floor or "").strip().lower()
    if not fl:
        return None
    env = os.environ.get("G2_FLOOR_POLICIES", "").strip()
    table = dict(kv.split("=", 1) for kv in env.split(",") if "=" in kv) if env else (_profile().get("floor_policies") or {})
    return table.get(fl) or None


def walk_choice(floor: str = "auto") -> tuple:
    """THE walking gait, decided in one place for every mode (owner, 2026-11-13): (kind, policy name or None, why). kind "policy" is the learned walk (through PolicyWalker; the name picks the policy file,
    None the attachment's own), "firmware" is Petoi's scripted walk (the arm's `wkArmF`). In order: a spoken gait ("high step" plays its policy; carpet and a scripted high step go through PolicyWalker as
    before); else the floor label (the arm on tile walks the V7 policy); else the default gait (scripted for the arm unless `G2_DEFAULT_GAIT=policy`)."""
    mode = current()
    pol = mode_policy(mode)
    if pol:
        return "policy", pol, f"{mode} gait: the {pol} policy"
    if mode != DEFAULT:
        return "policy", None, f"{mode} gait"
    if floor == "auto":
        try:
            from .heading_hold import current_floor
            floor = current_floor()
        except Exception:  # noqa: BLE001
            floor = None
    fp = floor_policy(floor)
    if fp:
        return "policy", fp, f"on {floor}: the {fp} policy"
    v = os.environ.get("G2_DEFAULT_GAIT", "").strip().lower()
    if not v:
        try:
            from ..config import settings
            v = settings.default_gait
        except Exception:  # noqa: BLE001
            v = "firmware"
    return ("policy", None, "the default gait is the learned walk") if v == "policy" else ("firmware", None, "the default gait is Petoi's scripted walk")


def policy_file(name: str | None) -> str | None:
    """The file of a learned policy by name: pi_pipeline/gait/ on the Pi, else trained/ on the dev machine (the same places the attachment profile looks). None when it is not there."""
    if not name:
        return None
    try:
        from pi_pipeline.attachments import _policy_file
        return _policy_file(name)
    except Exception:  # noqa: BLE001
        return None


def switching_allowed() -> bool:
    """False while the fitted attachment has `gait_switching` off (the arm's first tests, user 2026-10-24): the gait is held at normal whatever the state file says."""
    try:
        from pi_pipeline.attachments import flag_safe
    except ImportError:
        return True
    return flag_safe("gait_switching")


def _held_message() -> str:
    try:
        from pi_pipeline.attachments import current as _att
        what = f"the {_att()}"
    except ImportError:
        what = "this attachment"
    return f"Not with {what} fitted. I'm staying on my normal walk."


def current(path: str | None = None) -> str:
    mode = _read(path or STATE_PATH).get("mode", DEFAULT)
    return mode if mode in allowed_gaits() else DEFAULT


def blend(path: str | None = None, now: float | None = None) -> tuple[str, str, float]:
    """(from_gait, to_gait, alpha): alpha runs 0 -> 1 over BLEND_S after a switch, so the base is a mix of the old and new gait until then."""
    d = _read(path or STATE_PATH)
    if not d or d.get("mode") not in allowed_gaits():
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
    """For the voice loop and the exploration listener: (gait or None, the sentence to say). Always switches; a policy that does not list the gait plays its scripted base and says so."""
    gait = parse_gait_command(text)
    if gait is None:
        return None, ""
    if gait == DEFAULT:
        set_mode(DEFAULT, path)                           # "walk normally" always works (from the high step too)
        return DEFAULT, GAITS[DEFAULT].echo_on
    if gait not in allowed_gaits():                       # a gait this attachment is held away from: refused (None) with the reason
        return None, _held_message()
    set_mode(gait, path)
    if mode_policy(gait):                                 # the high step with a learned policy of its own (the arm: V7): played as that policy, no scripted base
        return gait, f"{GAITS[gait].echo_on} I am using my trained walking policy."
    if not supports(policy_onnx, gait):
        if not GAITS[gait].scripted_fallback:             # carpet on a policy that never learned it: its normal walk, said out loud
            return gait, f"{GAITS[gait].echo_on} My walk has not learned carpet yet, so I will use my normal walk for now."
        return gait, f"{GAITS[gait].echo_on} It is a scripted walk without my learned correction, so it is slow and experimental."   # the gait's scripted base, no learned correction
    return gait, GAITS[gait].echo_on


def uses_scripted(policy_onnx: str | None, gait: str) -> bool:
    """Whether a walk in `gait` is played as its scripted base: the policy never learned the gait and the gait falls back to its base (the high step), not to the normal walk (carpet)."""
    return gait != DEFAULT and not supports(policy_onnx, gait) and GAITS[gait].scripted_fallback


def follow_floor(label: str | None, path: str | None = None) -> str:
    """The floor label decides carpet mode (carpet plan, 2026-10-20): a carpet floor switches to it, any other floor switches out of it (another gait the person chose stays)."""
    cur = current(path)
    if "carpet" not in allowed_gaits():
        return cur                                         # this attachment has no carpet mode: the floor does not switch the gait (a gait the person chose stays)
    if (label or "").strip().lower() == "carpet":
        return set_mode("carpet", path) if cur != "carpet" else cur
    return set_mode(DEFAULT, path) if cur == "carpet" else cur


def floor_note(label: str | None, path: str | None = None) -> str:
    """follow_floor, plus what G2 adds after "Okay, the floor is ...": the gait change it made, if any."""
    before = current(path)
    after = follow_floor(label, path)
    if after != before:
        return " " + GAITS["carpet"].echo_on if after == "carpet" else " Back to my default gait."
    fp = floor_policy(label)
    if fp and after == DEFAULT:
        return " I will walk with my trained walking policy on this floor."          # the floor rule (the arm on tile: V7); a spoken gait still wins
    if (label or "").strip().lower() and (_profile().get("floor_policies") and after == DEFAULT):
        return " I will use my scripted walk on this floor."
    return ""


def split_compound(text: str):
    """'hi step and walk forward' -> ('hi_step', 'walk forward'): a gait command followed by "and (then) ..." asks for the gait first, then the rest; None otherwise."""
    m = re.match(r"^(.*?)\s+and\s+(?:then\s+)?(.+)$", (text or "").strip(), re.I)
    if not m:
        return None
    gait = parse_gait_command(m.group(1))
    return (gait, m.group(2)) if gait else None


def claude_hint() -> str:
    """One system-prompt line for Claude: G2's current walking gait, so a conversational walk uses it and never swaps in another skill."""
    mode = current()
    if allowed_gaits() == [DEFAULT]:
        return "Your walking gait is NORMAL and fixed while your attachment is fitted: the other gaits (hi step, carpet mode) are switched off for now."
    if mode == "carpet":
        return ("Your walking gait is set to CARPET MODE (for soft carpet). When asked to walk or go forward, use perform_skill walk_forward and it walks in carpet mode. "
                "The person switches back with 'switch to default gait'.")
    if mode == "hi_step" and mode_policy(mode):
        return ("Your walking gait is set to HI STEP, which for you is your trained walking policy. It is real: when asked to walk or go forward, use perform_skill walk_forward and it walks with that policy. "
                "Never substitute another skill for it. The person switches back with 'walk normally'.")
    if mode == "hi_step":
        return ("Your walking gait is set to HI STEP (a slow scripted high-stepping walk, lifted feet for snags and rubble). It is real: when asked to walk "
                "or go forward, use perform_skill walk_forward and it walks in hi step. Never substitute trot or another skill for it, and never say you do not have it. "
                "The person switches back with 'walk normally'.")
    return ("Your walking gait is NORMAL. You also have a HI STEP gait (a slow scripted high-stepping walk); the person switches to it by saying 'hi step' or "
            "'switch to high step', and a CARPET MODE for soft carpet ('carpet mode'). Never substitute trot for a gait you are asked for.")
