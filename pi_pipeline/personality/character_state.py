"""Runtime persistence for the opt-in character mode (e.g. `gir`).

`G2_CHARACTER` in `.env` is the *startup* default. This file is the *runtime*
override -- set when the user asks G2 to "enable gir mode" mid-conversation, so
the choice survives a restart. It takes precedence over the env var.

  load()               -> (name, level) or (None, None)
  save("gir", 0.4)     -> persist
  clear()              -> back to the env default

Stored next to the memory DB: `<G2_STATE_DIR or ~/.local/share/g2>/character.json`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _path() -> Path:
    base = os.environ.get("G2_STATE_DIR") or os.path.expanduser("~/.local/share/g2")
    return Path(base) / "character.json"


def load() -> tuple[str | None, float | None]:
    try:
        d = json.loads(_path().read_text())
        name = d.get("name")
        lvl = d.get("level")
        if name:
            return str(name).lower(), (float(lvl) if lvl is not None else None)
    except (OSError, ValueError, TypeError):
        pass
    return None, None


def save(name: str, level: float) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"name": name.lower(),
                             "level": max(0.0, min(1.0, float(level)))}))


def clear() -> None:
    try:
        _path().unlink()
    except OSError:
        pass
