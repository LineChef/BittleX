"""Head attachments (the Petoi AI head, the Petoi arm) and the gait policy saved for each.

G2 wears one attachment on the neck at a time. Which one is fitted is a single setting, read in this order:

    G2_ATTACHMENT=head                      # the environment (also from the repo .env) wins
    ~/.local/share/g2/attachment.json       # else the state file `python -m pi_pipeline.attachments use head` writes
    none                                    # else none

`none` (no attachment) never runs a firmware check and adds no skill. Until a gait is saved for it, it is exactly the behaviour G2 had
before attachments existed: the policy is `residual_policy.DEFAULT_POLICY` and the trim comes from `heading_hold.DEFAULT_TRIMS`.

For every attachment, `none` included, `gait_profiles.json` (next to this file) holds the gait saved for it: the current policy, its trim, the
sim payload it was trained on, and the earlier ones (last-known-good first when the current one cannot be used). A policy whose sidecar
(`<policy>.onnx.json`, field `payload_profile`) names a different sim payload than the attachment's is skipped. When nothing saved can be
used, the legacy `DEFAULT_POLICY` runs and the reason is logged.

Each attachment also names the BiBoard firmware model it needs (the first line of the `?` banner); `check_firmware` compares them. The
arm is a separate build of Petoi's firmware ("Bittle X+Arm", compile-time option `ROBOT_ARM`), so its skills are only offered when the
banner says so. The AI head accepts only the plain "Bittle X" build: the arm build shifts every posture and swaps the gaits (docs/planned/robot-arm.md).

A profile may also switch Pi behaviour off while that attachment is fitted (`flag`; a missing key means on): `easing` (the stock stand-up ramp and smoothing a skill's own motion) and `blending` (pose to pose: the link's move into a skill's first frame and the blend to balance at the end of a walk), `gyro_balance` (the firmware gyro balance: every `gB` becomes `gb`),
`gait_switching` (the gait stays normal; spoken gait commands are answered, not obeyed), `skills` (the attachment's own skills in the
conversation) and `fall_recovery` (the scripted self-right / roll-over / drop-recover moves are refused, link/opencat.py RECOVERY_SKILLS). The arm has all five off for its first hardware round (docs/plan-detail/arm-policy-plan.md).
Guide: docs/guides/attachments.md.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field

log = logging.getLogger("g2.attachments")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES_PATH = os.path.join(_HERE, "gait_profiles.json")
NONE = "none"


def state_path() -> str:
    """The state file `use` writes; G2_ATTACHMENT_FILE moves it (read on every call, so tests can point it at a temp file)."""
    return os.path.expanduser(os.environ.get("G2_ATTACHMENT_FILE", "~/.local/share/g2/attachment.json"))


@dataclass(frozen=True)
class Attachment:
    name: str
    description: str
    firmware_models: tuple[str, ...]          # accepted first lines of the BiBoard `?` banner; empty = no check
    skills: dict = field(default_factory=dict)  # extra entries for voice/skills.py SKILLS: name -> (token, description, continuous)
    checklist: tuple[str, ...] = ()            # what to do by hand when switching to it


# Petoi's arm page lists these tokens (docs/planned/robot-arm.md); none has been run on G2 yet.
_ARM_SKILLS = {
    "pick_up": ("pickF", "pick up the object in front with the claw", False),
    "put_down": ("putF", "put the held object down in front", False),
    "toss": ("tossF", "throw the held object forward", False),
    "show_off": ("showOff", "show off the held object", False),
    "clap": ("clap", "clap the claw", False),
}

ATTACHMENTS: dict[str, Attachment] = {
    NONE: Attachment(NONE, "no attachment on the neck (the stock head or nothing)", ()),
    "head": Attachment("head", "the Petoi AI head", ("Bittle X",),
                       checklist=("power G2 off", "fit the AI head on the neck servo", "Grove cable to the UART socket, the head's transmit line left unconnected")),
    "arm": Attachment("arm", "the Petoi robot arm (claw on the tail joint, index 2)", ("Bittle X+Arm",), skills=_ARM_SKILLS,
                      checklist=("power G2 off", "fit the arm on the neck servo (J-hook neck part, two M2x5 screws)",
                                 "the BiBoard must run the Bittle X+Arm firmware (Petoi Desktop App) and the claw must be calibrated (c-2)")),
}


def current() -> str:
    """The fitted attachment: G2_ATTACHMENT, else the state file, else none. An unknown name logs a warning and counts as none."""
    name = os.environ.get("G2_ATTACHMENT", "").strip().lower()
    if not name:
        try:
            name = str(json.load(open(state_path())).get("attachment", "")).strip().lower()
        except (OSError, ValueError, AttributeError):
            name = ""
    if not name:
        return NONE
    if name not in ATTACHMENTS:
        log.warning("unknown attachment %r (known: %s): using none", name, ", ".join(ATTACHMENTS))
        return NONE
    return name


def use(name: str, path: str | None = None) -> None:
    """Write the state file (the Pi's selection; G2_ATTACHMENT in the environment still overrides it)."""
    name = name.strip().lower()
    if name not in ATTACHMENTS:
        raise ValueError(f"unknown attachment {name!r}: use one of {', '.join(ATTACHMENTS)}")
    p = path or state_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"attachment": name, "set": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    os.replace(tmp, p)


# ---------------------------------------------------------------------------------------------------------------------- gait profiles

def load_profiles(path: str | None = None) -> dict:
    try:
        return json.load(open(path or PROFILES_PATH))
    except (OSError, ValueError):
        return {}


def save_profiles(data: dict, path: str | None = None) -> None:
    p = path or PROFILES_PATH
    with open(p + ".tmp", "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(p + ".tmp", p)


def _policy_file(name: str) -> str | None:
    """The same places residual_policy.default_policy_path looks: pi_pipeline/gait/ on the Pi, else trained/ on the dev machine."""
    gait = os.path.join(_HERE, "..", "gait", name)
    train = os.path.join(_HERE, "..", "..", "rl_training", "opencat-gym", "trained", name)
    return next((os.path.normpath(p) for p in (gait, train) if os.path.exists(p)), None)


def _sidecar_payload(path: str) -> str | None:
    try:
        return json.load(open(path + ".json")).get("payload_profile")
    except (OSError, ValueError, AttributeError):
        return None


@dataclass(frozen=True)
class GaitChoice:
    attachment: str
    path: str | None            # None = use the legacy DEFAULT_POLICY
    trim: str | None            # None = the legacy DEFAULT_TRIMS
    why: str
    trim_by_floor: dict = field(default_factory=dict)      # floor label -> trim, measured on that floor (`floor-trim`); wins over `trim` on that floor


def gait_for(attachment: str | None = None, profiles: dict | None = None) -> GaitChoice:
    """The policy and trim for an attachment. With nothing usable saved it returns path None: the caller keeps its legacy DEFAULT_POLICY
    path (for `none` with nothing saved, that is the behaviour from before attachments existed)."""
    att = attachment or current()
    prof = (profiles if profiles is not None else load_profiles()).get(att, {})
    if att == NONE and not prof.get("current") and not prof.get("history"):
        return GaitChoice(att, None, None, "no attachment, no gait saved for it: the legacy DEFAULT_POLICY")
    want = prof.get("payload_profile")
    entries = ([prof["current"]] if prof.get("current") else []) + list(reversed(prof.get("history", [])))
    skipped = []
    for i, e in enumerate(entries):
        name = e.get("policy", "")
        path = _policy_file(name) if name else None
        if path is None:
            skipped.append(f"{name or '?'}: file missing")
            continue
        got = _sidecar_payload(path) or e.get("payload_profile")
        if want and got and got != want:
            skipped.append(f"{name}: trained on payload {got}, {att} needs {want}")
            continue
        why = f"{att}: {'saved current' if i == 0 and prof.get('current') else 'last-known-good'} {name}" + (f" (skipped: {'; '.join(skipped)})" if skipped else "")
        if not got:
            why += " (its payload is not recorded)"
        return GaitChoice(att, path, e.get("trim"), why, dict(e.get("trim_by_floor") or {}))
    return GaitChoice(att, None, None, f"{att}: no usable saved gait ({'; '.join(skipped) or 'none saved'}), the legacy DEFAULT_POLICY")


_logged = set()


def policy_path_override() -> str | None:
    """For residual_policy.default_policy_path: the attachment's policy path, or None (keep the legacy path). Logs the choice once."""
    g = gait_for(current())
    if g.path is None and g.attachment == NONE:
        return None                                    # the legacy path, silently, exactly as before attachments existed
    if g.why not in _logged:
        _logged.add(g.why)
        (log.info if g.path else log.warning)("gait for attachment %s", g.why)
    return g.path


def trim_override(policy_name: str | None) -> str | None:
    """For heading_hold.default_foot_trim: the trim saved with this policy for the fitted attachment, or None (keep DEFAULT_TRIMS)."""
    if not policy_name:
        return None
    g = gait_for(current())
    if g.path and os.path.basename(g.path) == os.path.basename(str(policy_name)):
        return g.trim
    return None


def floor_trim_override(policy_name: str | None, floor: str | None) -> str | None:
    """For heading_hold.default_foot_trim: the trim measured on `floor` for this policy and the fitted attachment, or None (no per-floor trim saved)."""
    if not policy_name or not floor or floor == "unknown":
        return None
    g = gait_for(current())
    if g.path and os.path.basename(g.path) == os.path.basename(str(policy_name)):
        return g.trim_by_floor.get(floor)
    return None


def set_floor_trim(attachment: str, floor: str, trim: str | None, path: str | None = None) -> dict:
    """Save (or with `trim` None, remove) the trim measured on `floor` for the attachment's current gait."""
    data = load_profiles(path)
    cur = (data.get(attachment) or {}).get("current")
    if not cur:
        raise ValueError(f"{attachment} has no saved current gait; save one first (`save {attachment} POLICY`)")
    floor = "-".join(str(floor).strip().lower().split())
    tbf = dict(cur.get("trim_by_floor") or {})
    if trim is None:
        tbf.pop(floor, None)
    else:
        tbf[floor] = trim
    cur["trim_by_floor"] = tbf
    save_profiles(data, path)
    return cur


def register(attachment: str, policy: str, *, trim: str | None = None, payload_profile: str | None = None, note: str = "",
             path: str | None = None) -> dict:
    """Make `policy` the attachment's current gait; the previous current moves to the history (the last-known-good)."""
    if attachment not in ATTACHMENTS:
        raise ValueError(f"gaits are saved for {', '.join(ATTACHMENTS)}, not {attachment!r}")
    data = load_profiles(path)
    prof = data.setdefault(attachment, {"payload_profile": payload_profile, "current": None, "history": []})
    if payload_profile:
        prof["payload_profile"] = prof.get("payload_profile") or payload_profile
    if prof.get("current"):
        prof.setdefault("history", []).append(prof["current"])
    prof["current"] = {"policy": os.path.basename(policy), "trim": trim, "payload_profile": payload_profile or prof.get("payload_profile"),
                       "saved": time.strftime("%Y-%m-%d"), "note": note}
    save_profiles(data, path)
    return prof


def flag(key: str, attachment: str | None = None, profiles: dict | None = None) -> bool:
    """A behaviour switch from the fitted attachment's profile (easing, gyro_balance, gait_switching, skills): on unless the profile says false."""
    att = attachment or current()
    v = ((profiles if profiles is not None else load_profiles()).get(att) or {}).get(key)
    return True if v is None else bool(v)


def flag_safe(key: str) -> bool:
    """`flag` for the gait and link code, which must never fail on it: any error logs and counts as on (the behaviour from before profiles had switches)."""
    try:
        return flag(key)
    except Exception as e:  # noqa: BLE001
        log.warning("attachment switch %s unreadable (%s): on", key, e)
        return True


# ---------------------------------------------------------------------------------------------------------------------- firmware

def check_firmware(banner: str, attachment: str | None = None) -> tuple[bool, str]:
    """Compare the first line of the BiBoard's `?` banner with what the attachment needs."""
    att = attachment or current()
    want = ATTACHMENTS[att].firmware_models
    if not want:
        return True, "no firmware requirement"
    first = next((l.strip() for l in str(banner or "").splitlines() if l.strip()), "")
    if first in want:
        return True, f"firmware {first!r} fits {att}"
    return False, f"firmware {first or 'did not answer'!r}: {att} needs {' or '.join(repr(w) for w in want)}"


def skills_for(attachment: str | None = None) -> dict:
    return dict(ATTACHMENTS[attachment or current()].skills)


VOICE_RESET_GAP_S = 1.2                    # the voice module needs about this long between X commands (the 2026-09-28 recovery)


DEFAULT_VOICE_LANGUAGE = "english"         # used when a profile (or the whole profile file) is missing or unreadable, so the board is set to English even when the profile fails


def voice_module_language(attachment: str | None = None, profiles: dict | None = None) -> str | None:
    """The language the BiBoard's voice module is set to at start-up: the attachment's profile (gait_profiles.json, key `voice_module_language`), else English.
    "off" in the profile turns it off (None)."""
    att = attachment or current()
    value = ((profiles if profiles is not None else load_profiles()).get(att) or {}).get("voice_module_language")
    value = value.strip().lower() if isinstance(value, str) and value.strip() else DEFAULT_VOICE_LANGUAGE
    return None if value == "off" else value


def apply_voice_module_language(link, attachment: str | None = None) -> bool:
    """Send the profile's voice-module language to the BiBoard: `XAc` (enable), a pause, then `XAa` (English). Only English is supported; any other value is logged and ignored.
    Returns whether the commands were sent. Never raises."""
    att = attachment or current()
    want = voice_module_language(att)
    if want is None or link is None:
        return False
    if want != "english":
        log.warning("attachment %s: voice_module_language %r is not supported (only 'english'); nothing sent", att, want)
        return False
    try:
        from ..link import opencat
        link.send(opencat.VOICE_MODULE_ENABLE, read_reply=True)         # the board answers every X command with a stray 'X': read it so the later `?` reads the real banner
        time.sleep(VOICE_RESET_GAP_S)
        link.send(opencat.VOICE_MODULE_ENGLISH, read_reply=True)
    except Exception as e:  # noqa: BLE001 -- must never stop the service
        log.warning("attachment %s: could not set the voice module to English (%s)", att, e)
        return False
    log.info("attachment %s: BiBoard voice module set to English (profile)", att)
    return True


def startup_check(link) -> bool | None:
    """Called once at start-up by the voice service and the app, with the shared serial link (or None). Attachment `none`: sets only the voice
    module's language (no `?`, no skills; returns None). Otherwise logs the attachment and its gait, sets the voice module's language when the profile says so, asks the BiBoard `?`, and when the firmware does not
    fit, logs it and takes the attachment's skills back out. Returns whether the firmware fits (None when nothing was checked)."""
    att = current()
    apply_voice_module_language(link, att)         # every profile says English (the module falls back to Chinese after some power cycles): sent for `none` too, before anything else talks to the board
    if att == NONE:
        return None
    log.info("attachment: %s (%s); gait: %s", att, ATTACHMENTS[att].description, gait_for(att).why)
    if link is None or not ATTACHMENTS[att].firmware_models:
        return None
    try:
        from ..link import opencat
        banner = link.send(opencat.QUERY, read_reply=True)
    except Exception as e:  # noqa: BLE001 -- a failed query must never stop the service
        log.warning("attachment %s: could not ask the BiBoard its firmware (%s)", att, e)
        return None
    ok, msg = check_firmware(banner, att)
    if ok:
        log.info("attachment %s: %s", att, msg)
        if not flag("gyro_balance", att):
            link.send("gb", read_reply=False, settle=0.0)          # the firmware boots with its gyro balance on; this attachment runs with it off
            log.info("attachment %s: firmware gyro balance off (profile)", att)
        return True
    from ..voice import skills
    gone = skills.remove_attachment_skills()
    log.warning("attachment %s: %s%s", att, msg, f"; its skills are off ({', '.join(gone)})" if gone else "")
    return False
