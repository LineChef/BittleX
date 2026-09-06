"""Feature flags for staged bring-up.

Every major subsystem sits behind a flag so it can be turned on one at a time
during hardware bring-up -- if something breaks, it's the thing you just enabled.
Once past bring-up the default (empty `G2_FEATURES`) is everything on.

    from pi_pipeline.features import features
    if features.memory: ...
    if features.gait == "policy": ...

Configure via `G2_FEATURES` in `.env`:

    G2_FEATURES="profile:p2-gait"
    G2_FEATURES="profile:p3-safety, +vision_perception, -thermal_guard"
    G2_FEATURES="-explore, gait:scripted"          # no profile -> start from full

Tokens: `profile:<name>` (first token; base to build on), `+flag` / `-flag`
(bool flags), `field:value` (the three modes: `gait`, `fall_detect`,
`power_profile`). Unknown tokens warn and are skipped.

`Features.resolve()` applies dependency rules (e.g. no `gait` -> no `explore`)
and returns the adjusted set plus the list of adjustments made -- the app logs
both at startup so every session records exactly what ran.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, fields, replace

log = logging.getLogger("g2.features")

_GAIT = ("off", "scripted", "policy")
_FALL = ("off", "alert", "act")
_POWER = ("off", "interactive", "headless")
_MODE_FIELDS = {"gait": _GAIT, "fall_detect": _FALL, "power_profile": _POWER}


@dataclass(frozen=True)
class Features:
    # -- layer 0: foundation --
    link: bool = True
    estop: bool = False                 # master safe-hold; forces actuation off
    # -- layer 1: sensing --
    imu: bool = True
    fall_detect: str = "act"            # off | alert | act
    vision_safety: bool = True          # cliff/edge + obstacle (safety-critical)
    vision_perception: bool = True      # scene / object / individual recognition
    mic: bool = True
    wake_word: bool = True
    # -- layer 2: actuation --
    gait: str = "policy"               # off | scripted | policy
    thermal_guard: bool = True
    sound_cues: bool = True
    leds: bool = True
    # -- layer 3: cognition --
    stt: bool = True
    tts: bool = True
    claude: bool = True
    memory: bool = True
    personality: bool = True
    # -- layer 4: autonomy --
    mode_controller: bool = True
    explore: bool = True
    idle_rest: bool = True
    avoidance_act: bool = True          # vision avoidance drives the actuator
    # -- cross-cutting --
    power_profile: str = "headless"    # off | interactive | headless
    diag: bool = True                  # black-box logging; kept on for bring-up

    # ------------------------------------------------------------------ build

    @classmethod
    def from_spec(cls, spec: str) -> "Features":
        return _parse(spec)

    @classmethod
    def from_settings(cls, settings) -> "Features":
        return _parse(getattr(settings, "features_spec", ""))

    # --------------------------------------------------------------- resolve

    def resolve(self) -> tuple["Features", list[str]]:
        """Apply dependency rules. Returns (adjusted, notes)."""
        f = self
        notes: list[str] = []

        def off(**kw):
            nonlocal f
            f = replace(f, **kw)

        if f.estop:
            if f.gait != "off" or f.explore or f.idle_rest or f.avoidance_act \
                    or f.fall_detect == "act":
                off(gait="off", explore=False, idle_rest=False, avoidance_act=False,
                    fall_detect="alert" if f.fall_detect != "off" else "off")
                notes.append("estop engaged -> all actuation/autonomy held")

        if not f.link:
            if f.gait != "off" or f.fall_detect != "off":
                off(gait="off", fall_detect="off")
                notes.append("no link -> gait off, fall_detect off")
        if not f.imu and (f.gait == "policy" or f.fall_detect != "off"):
            off(gait="scripted" if f.gait == "policy" else f.gait, fall_detect="off")
            notes.append("no imu -> gait can't run the policy, fall_detect off")

        if f.gait == "off":
            if f.explore or f.idle_rest or f.avoidance_act or f.thermal_guard:
                off(explore=False, idle_rest=False, avoidance_act=False,
                    thermal_guard=False)
                notes.append("gait off -> explore/idle_rest/avoidance_act/thermal_guard off")

        if not f.vision_safety and (f.avoidance_act or f.explore):
            off(avoidance_act=False, explore=False)
            notes.append("no vision_safety -> avoidance_act off, explore off (don't wander blind)")

        if not f.mic and (f.stt or f.wake_word):
            off(stt=False, wake_word=False)
            notes.append("no mic -> stt off, wake_word off")
        if f.wake_word and not f.stt:
            notes.append("wake_word on without stt -- wake fires but nothing transcribes")

        if f.explore and not f.mode_controller:
            notes.append("explore on without mode_controller -- usually driven by it")
        if f.claude and not (f.stt or f.tts):
            notes.append("claude on without stt/tts -- text-mode only")

        return f, notes

    # ----------------------------------------------------------- introspect

    def enabled(self, name: str) -> bool:
        v = getattr(self, name, False)
        return bool(v) if isinstance(v, bool) else v not in ("", "off")

    def describe(self) -> str:
        rows = []
        for grp, names in _GROUPS:
            parts = []
            for n in names:
                v = getattr(self, n)
                if isinstance(v, bool):
                    parts.append(f"{'+' if v else '-'}{n}")
                else:
                    parts.append(f"{n}:{v}")
            rows.append(f"  {grp:12} {'  '.join(parts)}")
        return "\n".join(rows)


_GROUPS = [
    ("foundation", ["link", "estop"]),
    ("sensing", ["imu", "fall_detect", "vision_safety", "vision_perception", "mic", "wake_word"]),
    ("actuation", ["gait", "thermal_guard", "sound_cues", "leds"]),
    ("cognition", ["stt", "tts", "claude", "memory", "personality"]),
    ("autonomy", ["mode_controller", "explore", "idle_rest", "avoidance_act"]),
    ("cross", ["power_profile", "diag"]),
]

_ALL_BOOL = {f.name for f in fields(Features) if f.type == "bool"}


# ---------------------------------------------------------------- profiles

_OFF = dict(
    link=False, estop=False, imu=False, fall_detect="off",
    vision_safety=False, vision_perception=False, mic=False, wake_word=False,
    gait="off", thermal_guard=False, sound_cues=False, leds=False,
    stt=False, tts=False, claude=False, memory=False, personality=False,
    mode_controller=False, explore=False, idle_rest=False, avoidance_act=False,
    power_profile="off", diag=True,
)

# each stage = the previous + these keys
_STAGES = [
    ("p0-link", {"link": True}),
    ("p1-sensing", {"imu": True, "fall_detect": "alert"}),
    ("p2-gait", {"fall_detect": "act", "gait": "scripted", "thermal_guard": True,
                 "leds": True, "sound_cues": True}),
    ("p3-safety", {"vision_safety": True, "avoidance_act": True}),
    ("p4-perception", {"vision_perception": True}),
    ("p5-voice", {"mic": True, "stt": True, "tts": True, "claude": True}),
    ("p6-wake", {"wake_word": True}),
    ("p7-memory", {"memory": True, "personality": True}),
    ("p8-autonomy", {"mode_controller": True, "explore": True, "idle_rest": True}),
    ("p9-full", {"gait": "policy", "power_profile": "headless"}),
]


def _build_profiles() -> dict[str, dict]:
    out: dict[str, dict] = {}
    acc = dict(_OFF)
    for name, delta in _STAGES:
        acc = {**acc, **delta}
        out[name] = dict(acc)
    return out


PROFILES = _build_profiles()
DEFAULT_PROFILE = "p9-full"


def _match_profile(name: str) -> str | None:
    name = name.strip().lower()
    if name in PROFILES:
        return name
    hits = [p for p in PROFILES if p.split("-")[0] == name or p.startswith(name)]
    return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------------- parse

def _parse(spec: str) -> Features:
    spec = (spec or "").strip()
    base = dict(PROFILES[DEFAULT_PROFILE])
    tokens = [t.strip() for t in spec.split(",") if t.strip()]

    if tokens and tokens[0].lower().startswith("profile:"):
        pname = tokens[0].split(":", 1)[1]
        matched = _match_profile(pname)
        if matched:
            base = dict(PROFILES[matched])
        else:
            log.warning("features: unknown profile %r -- using %s (known: %s)",
                        pname, DEFAULT_PROFILE, ", ".join(PROFILES))
        tokens = tokens[1:]

    for tok in tokens:
        low = tok.lower()
        if low.startswith("profile:"):
            log.warning("features: 'profile:' must be the first token -- %r ignored", tok)
            continue
        if tok.startswith("+") or tok.startswith("-"):
            name = tok[1:].strip()
            if name in _ALL_BOOL:
                base[name] = tok.startswith("+")
            else:
                log.warning("features: unknown flag %r -- skipped", name)
            continue
        if ":" in tok:
            field, _, val = tok.partition(":")
            field, val = field.strip(), val.strip().lower()
            if field in _MODE_FIELDS:
                if val in _MODE_FIELDS[field]:
                    base[field] = val
                else:
                    log.warning("features: %s must be one of %s -- %r skipped",
                                field, _MODE_FIELDS[field], val)
            else:
                log.warning("features: unknown mode field %r -- skipped", field)
            continue
        log.warning("features: unparseable token %r -- skipped", tok)

    return Features(**base)


# ------------------------------------------------------------------ singleton

_features: Features | None = None
_notes: list[str] = []


def load(settings=None) -> Features:
    """Resolve the feature set once, from settings (or the process env). Cached."""
    global _features, _notes
    if _features is None:
        if settings is None:
            from .config import settings as _s
            settings = _s
        raw = Features.from_settings(settings)
        _features, _notes = raw.resolve()
    return _features


def log_summary(logger: logging.Logger | None = None) -> None:
    f = load()
    lg = logger or log
    lg.info("features resolved:\n%s", f.describe())
    for n in _notes:
        lg.warning("features: %s", n)
    try:                       # optional, don't hard-depend on diag
        from .diag import diag
        diag.event("features", "INFO", "resolved",
                   flags={k: getattr(f, k) for k in
                          (fld.name for fld in fields(Features))},
                   adjustments=_notes)
    except Exception:          # noqa: BLE001
        pass


class _Proxy:
    """Attribute access that resolves the singleton lazily: `features.memory`."""

    def __getattr__(self, name):
        return getattr(load(), name)

    def __repr__(self):  # pragma: no cover
        return repr(load())


features = _Proxy()
