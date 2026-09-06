"""Per-individual **bonds** -- how G2 relates to specific people and pets it can
recognise (B15).

A `Bond` pairs a recognised vision label (a household member's or pet's own
detection class) with two numbers the behaviour layer will read:

- **closeness** in [0, 1] -- how much G2 seeks that individual out, how warm it
  is, how much of their memory context gets pulled. Seeded from config, drifts
  a little with interaction *within a session* (not yet persisted -- that's a
  follow-up).
- **disposition** -- one of six stances that set an *approach bias*: whether G2
  moves toward the individual, holds, or opens distance when it sees them.

This module is **API only**. It parses `G2_BONDS`, answers `disposition_for` /
`closeness_for` / `seek_bias_for`, and drifts closeness via `note_interaction`.
Wiring the approach bias into the Explorer / greeting layer is a separate,
reviewed change -- nothing here imports or mutates the behaviour modules.

The household roster is per-deployment **personal data**: it lives only in the
gitignored `.env` (`G2_BONDS`), never in a tracked file. Recognition itself runs
on-chip on the vision module; only labels leave it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger("g2.personality.bonds")

# closeness a never-before-seen person starts at (they default to `curious`).
NEW_PERSON_CLOSENESS = 0.10
# how fast closeness moves toward an interaction's valence, per `note_interaction`.
DRIFT_RATE = 0.05

# generic detector labels that mean "a person, but we don't know which one"
_PERSON_LABELS = {"person", "people", "face", "human"}


class Disposition(Enum):
    """G2's stance toward an individual. `approach_bias` is a scalar in
    [-1, 1]: +1 seek out and greet, 0 orient but hold, -1 actively avoid.
    Values are v1 first-guesses -- tune once the behaviour wiring exists."""

    AFFECTIONATE = "affectionate"
    PLAYFUL = "playful"
    CURIOUS = "curious"
    NEUTRAL = "neutral"
    WARY = "wary"
    FEARFUL = "fearful"

    @classmethod
    def parse(cls, raw: str) -> "Disposition":
        key = (raw or "").strip().lower()
        for d in cls:
            if d.value == key:
                return d
        if key:
            log.warning("bonds: unknown disposition %r -- using neutral", raw)
        return cls.NEUTRAL

    @property
    def approach_bias(self) -> float:
        return {
            Disposition.AFFECTIONATE: 1.0,
            Disposition.PLAYFUL: 0.7,
            Disposition.CURIOUS: 0.5,
            Disposition.NEUTRAL: 0.0,
            Disposition.WARY: -0.6,
            Disposition.FEARFUL: -1.0,
        }[self]

    @property
    def avoids_on_sight(self) -> bool:
        """True only for `fearful` -- the behaviour layer should suppress
        wandering toward this individual's bearing the instant it's seen, not
        just react afterwards. The stronger "bias wander headings away from its
        last-known position" logic is deferred to the behaviour-wiring pass;
        this flag is the hook for it."""
        return self is Disposition.FEARFUL


@dataclass
class Bond:
    label: str                       # vision class label, lower-cased
    disposition: Disposition = Disposition.NEUTRAL
    closeness: float = 0.5
    kind: str = "person"             # "person" | "pet"
    seed_closeness: float = field(default=0.5)

    def __post_init__(self) -> None:
        self.label = self.label.strip().lower()
        self.kind = (self.kind or "person").strip().lower() or "person"
        self.closeness = _clamp01(self.closeness)
        self.seed_closeness = _clamp01(self.seed_closeness)

    @property
    def seek_bias(self) -> float:
        """Approach bias modulated by closeness: a warm disposition still pulls
        harder for someone G2 is close to, but a `fearful`/`wary` stance keeps
        its full magnitude regardless. v1 shaping -- tunable."""
        b = self.disposition.approach_bias
        if b > 0:
            return b * (0.4 + 0.6 * self.closeness)
        return b

    def drift(self, valence: float) -> None:
        """Move closeness toward an interaction's valence (-1 bad .. +1 good).
        In-session only; not persisted yet."""
        target = 0.5 + 0.5 * max(-1.0, min(1.0, valence))
        self.closeness = _clamp01(self.closeness + DRIFT_RATE * (target - self.closeness))

    def reset_drift(self) -> None:
        self.closeness = self.seed_closeness


def _clamp01(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5


def parse_bonds(spec: str) -> list[Bond]:
    """`"self:1.0:affectionate; sam:0.7:playful:person; rex:0.4:wary:pet"` ->
    [Bond, ...]. Fields: `name:closeness:disposition[:kind]`, `;`-separated.
    Tolerant: blank -> [], missing closeness/disposition -> defaults + a warning,
    duplicate name -> last wins."""
    out: dict[str, Bond] = {}
    for entry in (spec or "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split(":")]
        name = parts[0].lower()
        if not name:
            continue
        closeness = _clamp01(parts[1]) if len(parts) > 1 and parts[1] != "" else 0.5
        disp = Disposition.parse(parts[2]) if len(parts) > 2 else Disposition.NEUTRAL
        kind = parts[3].lower() if len(parts) > 3 and parts[3] else "person"
        out[name] = Bond(
            label=name, disposition=disp, closeness=closeness,
            kind=kind, seed_closeness=closeness,
        )
    return list(out.values())


class Bonds:
    """The set of known bonds, plus the defaults for anyone unrecognised."""

    def __init__(self, bonds: list[Bond] | None = None):
        self._by_label: dict[str, Bond] = {b.label: b for b in (bonds or [])}

    @classmethod
    def from_spec(cls, spec: str) -> "Bonds":
        return cls(parse_bonds(spec))

    @classmethod
    def from_settings(cls, settings) -> "Bonds":
        return cls.from_spec(getattr(settings, "bonds_spec", ""))

    # --- lookup ---

    def get(self, label: str) -> Bond | None:
        return self._by_label.get((label or "").strip().lower())

    def __contains__(self, label: str) -> bool:
        return self.get(label) is not None

    def __iter__(self):
        return iter(self._by_label.values())

    def __len__(self) -> int:
        return len(self._by_label)

    @staticmethod
    def _is_person_label(label: str) -> bool:
        return (label or "").strip().lower() in _PERSON_LABELS

    def disposition_for(self, label: str) -> Disposition:
        """Known individual -> their disposition. An unrecognised *person*
        (generic "person" detection, or a name with no bond) -> `curious`
        (B15: new people get approached, not held at arm's length). Anything
        else unrecognised -> `neutral`."""
        b = self.get(label)
        if b is not None:
            return b.disposition
        if self._is_person_label(label):
            return Disposition.CURIOUS
        return Disposition.NEUTRAL

    def closeness_for(self, label: str) -> float:
        b = self.get(label)
        if b is not None:
            return b.closeness
        if self._is_person_label(label):
            return NEW_PERSON_CLOSENESS
        return 0.0

    def seek_bias_for(self, label: str) -> float:
        """Net approach bias for a detection label, in [-1, 1]. This is the one
        number the Explorer/greeting layer will consume once wired."""
        b = self.get(label)
        if b is not None:
            return b.seek_bias
        d = self.disposition_for(label)
        c = self.closeness_for(label)
        base = d.approach_bias
        return base * (0.4 + 0.6 * c) if base > 0 else base

    def avoids_on_sight(self, label: str) -> bool:
        return self.disposition_for(label).avoids_on_sight

    # --- drift ---

    def note_interaction(self, label: str, valence: float) -> None:
        """Nudge a *known* individual's closeness toward `valence`
        (-1 bad .. +1 good). No-op for unrecognised labels -- a generic
        "person" hit can't own a per-individual bond, and per-stranger
        ephemeral bonds need a model that gives each new face its own class
        (hook, not built)."""
        b = self.get(label)
        if b is None:
            log.debug("bonds: note_interaction for unknown label %r -- ignored", label)
            return
        b.drift(valence)

    def reset_drift(self) -> None:
        for b in self._by_label.values():
            b.reset_drift()

    # --- introspection ---

    def describe(self) -> str:
        if not self._by_label:
            return "(no bonds)"
        return ", ".join(
            f"{b.label}[{b.kind}] {b.disposition.value} c={b.closeness:.2f}"
            for b in self._by_label.values()
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Bonds([{self.describe()}])"
