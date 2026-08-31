"""Central configuration for the Pi pipeline, loaded from environment variables.

Values come from the process environment; `.env` at the repo root is loaded first
if present (via python-dotenv). Nothing here is secret except the API key, which
never has a default.

Usage:
    from pi_pipeline.config import settings
    settings.claude_model
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional at import time so `--help` etc. work without the dep installed
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_kw):  # type: ignore
        return False

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    return int(raw) if raw else default


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    return float(raw) if raw else default


_DEFAULT_SYSTEM_PROMPT = (
    "You are G2, a small four-legged robot companion (a Petoi Bittle X). "
    "You are curious, warm, and a little playful. Keep replies short and "
    "conversational -- one or two sentences -- because everything you say is "
    "spoken aloud through a small speaker. Do not use markdown, lists, or "
    "emoji. When it fits naturally, you can move: use the perform_skill tool to "
    "sit, walk, wave, and so on. You have persistent memory of past "
    "conversations when it is provided to you."
)


@dataclass(frozen=True)
class Settings:
    # --- Claude ---
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-sonnet-5"))
    claude_max_tokens: int = field(default_factory=lambda: _env_int("CLAUDE_MAX_TOKENS", 400))
    request_timeout_s: float = field(default_factory=lambda: _env_float("CLAUDE_TIMEOUT_S", 30.0))
    system_prompt: str = field(default_factory=lambda: _env("G2_SYSTEM_PROMPT") or _DEFAULT_SYSTEM_PROMPT)
    history_turns: int = field(default_factory=lambda: _env_int("G2_HISTORY_TURNS", 12))

    # --- Voice I/O ---
    wake_word: str = field(default_factory=lambda: _env("G2_WAKE_WORD", "hey gee two"))
    vosk_model_path: str = field(default_factory=lambda: _env("VOSK_MODEL_PATH", "models/vosk"))
    piper_model_path: str = field(default_factory=lambda: _env("PIPER_MODEL_PATH", "models/piper/en_GB-alan-medium.onnx"))
    stt_silence_s: float = field(default_factory=lambda: _env_float("G2_STT_SILENCE_S", 1.2))

    # --- Memory (Phase 9) ---
    memory_enabled: bool = field(default_factory=lambda: _env("G2_MEMORY", "1") not in ("0", "false", "no"))
    memory_db_path: str = field(default_factory=lambda: _env("G2_MEMORY_DB", "pi_pipeline/memory/data/g2_memory.db"))
    memory_max_facts: int = field(default_factory=lambda: _env_int("G2_MEMORY_MAX_FACTS", 30))
    memory_recall_exchanges: int = field(default_factory=lambda: _env_int("G2_MEMORY_RECALL", 3))

    # --- Robot link (used on hardware; ignored by MockActuator) ---
    serial_port: str = field(default_factory=lambda: _env("G2_SERIAL_PORT", "/dev/ttyS0"))
    serial_baud: int = field(default_factory=lambda: _env_int("G2_SERIAL_BAUD", 115200))

    # --- Vision (Phase 8; used on hardware) ---
    vision_serial_port: str = field(default_factory=lambda: _env("VISION_SERIAL_PORT", "/dev/ttyAMA1"))
    vision_serial_baud: int = field(default_factory=lambda: _env_int("VISION_SERIAL_BAUD", 921600))

    def require_api_key(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env at the "
                "repo root and fill it in."
            )
        return self.anthropic_api_key


settings = Settings()
