"""Central configuration for the Pi pipeline, loaded from environment variables.

Values come from the process environment; `.env` at the repo root is loaded first
if present (via python-dotenv). Nothing here is secret except the API key, which
never has a default.

Usage:
    from pi_pipeline.config import settings
    settings.claude_model
"""
from __future__ import annotations

import datetime as _dt
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
    "You are warm and friendly. Keep replies short and conversational -- one or "
    "two sentences -- because everything you say is spoken aloud through a small "
    "speaker. Do not use markdown, lists, or emoji. When it fits naturally, you "
    "can move: use the perform_skill tool to sit, walk, wave, and so on. When "
    "you are not asked to do anything in particular, a small natural reaction "
    "makes you feel alive: nod for yes or understanding, shake_head for no, "
    "disagreement or confusion, check_around when you are thinking something "
    "over or inspecting -- at most one reaction per reply. You "
    "have persistent memory of past conversations when it is provided to you."
)
# Personality beyond "warm and friendly" comes from traits (G2_TRAITS ->
# pi_pipeline.personality), appended to this prompt at conversation start.


@dataclass(frozen=True)
class Settings:
    # One field per env var; see the module docstring for how values are loaded.
    # --- Claude ---
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    # ISO date (YYYY-MM-DD) you set the console key to expire on -- G2 warns as it
    # nears, and says clearly once it's past, so an expired key is never a silent
    # "why won't it answer". Empty = no check.
    api_key_expires: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY_EXPIRES"))
    api_key_expiry_warn_days: int = field(
        default_factory=lambda: _env_int("G2_API_KEY_EXPIRY_WARN_DAYS", 30))
    # What G2 says out loud when a Claude call fails for a *known* reason (so it
    # isn't the generic "I glitched"). Override in .env to reword in character.
    speech_api_auth: str = field(default_factory=lambda: _env(
        "G2_SPEECH_API_AUTH",
        "I can't reach my brain right now -- my API key may be invalid or expired."))
    speech_api_rate: str = field(default_factory=lambda: _env(
        "G2_SPEECH_API_RATE",
        "I'm being rate-limited. Give me a moment and try again."))
    speech_api_billing: str = field(default_factory=lambda: _env(
        "G2_SPEECH_API_BILLING",
        "I've hit my usage limit and can't chat right now."))
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-sonnet-5-5"))
    claude_max_tokens: int = field(default_factory=lambda: _env_int("CLAUDE_MAX_TOKENS", 400))
    # Thinking depth: low | medium | high | xhigh | max. "low" keeps spoken replies quick and stops thinking
    # tokens from eating the small max_tokens budget. Empty = the model's own default.
    claude_effort: str = field(default_factory=lambda: _env("G2_CLAUDE_EFFORT", "low").lower())
    # --- Swappable LLM (see voice/llm.py, docs/guides/swappable-llm.md) ---
    # claude (default) | fast (OpenAI-style backend only, no Anthropic key needed) | routed (fast for casual turns, Claude for the rest)
    llm_mode: str = field(default_factory=lambda: _env("G2_LLM_MODE", "claude").lower())
    fast_llm_base_url: str = field(default_factory=lambda: _env("G2_FAST_LLM_BASE_URL"))
    fast_llm_api_key: str = field(default_factory=lambda: _env("G2_FAST_LLM_API_KEY"))
    fast_llm_model: str = field(default_factory=lambda: _env("G2_FAST_LLM_MODEL"))
    # Memory context is personal; by default it never goes to the fast backend (such turns go to Claude).
    fast_llm_sees_memory: bool = field(default_factory=lambda: _env("G2_FAST_LLM_SEES_MEMORY").lower() in ("1", "true", "yes", "on"))
    route_max_words: int = field(default_factory=lambda: _env_int("G2_ROUTE_MAX_WORDS", 25))
    route_escalate_pattern: str = field(default_factory=lambda: _env("G2_ROUTE_ESCALATE_PATTERN"))
    request_timeout_s: float = field(default_factory=lambda: _env_float("CLAUDE_TIMEOUT_S", 30.0))
    system_prompt: str = field(default_factory=lambda: _env("G2_SYSTEM_PROMPT") or _DEFAULT_SYSTEM_PROMPT)
    history_turns: int = field(default_factory=lambda: _env_int("G2_HISTORY_TURNS", 12))

    # --- Feature flags (staged bring-up) ---
    # empty = everything on. e.g. "profile:p2-gait" or "-explore, gait:scripted".
    # Parsed by pi_pipeline.features; run `python -m pi_pipeline.features` to check.
    features_spec: str = field(default_factory=lambda: _env("G2_FEATURES", ""))

    # --- Personality (traits that bias prompt / behaviour / cues) ---
    # comma-separated name=level, e.g. "curiosity=0.85, playfulness=0.4"
    traits_spec: str = field(default_factory=lambda: _env("G2_TRAITS", "curiosity=0.8"))
    # Opt-in "character mode" -- OFF by default. Set G2_CHARACTER=gir to turn it
    # on; G2_CHARACTER_LEVEL sets the 0..1 intensity (default 0.4). An explicit
    # entry in G2_TRAITS still wins over this.
    character_spec: str = field(default_factory=lambda: _env("G2_CHARACTER", ""))
    character_level: float = field(default_factory=lambda: _env_float("G2_CHARACTER_LEVEL", 0.4))
    # Household roster for B15 -- PERSONAL DATA, real values only in the
    # gitignored .env. Format: name:closeness:disposition[:kind], ';'-separated.
    # disposition = affectionate|playful|curious|wary|fearful|neutral; kind =
    # person|pet (default person). Parsed by personality.bonds.
    bonds_spec: str = field(default_factory=lambda: _env("G2_BONDS", ""))

    # --- Voice I/O ---
    # Comma-separated -- any one of them wakes G2. Spelled the way Vosk
    # transcribes each phrase, not necessarily how it's written ("gee two", not
    # "G2").
    wake_word: str = field(default_factory=lambda: _env("G2_WAKE_WORD", "gee two, hey buddy, hey bud"))
    vosk_model_path: str = field(default_factory=lambda: _env("VOSK_MODEL_PATH", "models/vosk"))
    # Default = the Pi Zero 2 W-safe 'low' tier (fetch_models.sh's primary). On a
    # dev machine, override PIPER_MODEL_PATH in .env to a 'medium' voice if you
    # want it to sound nicer -- the Pi can't afford one.
    piper_model_path: str = field(default_factory=lambda: _env("PIPER_MODEL_PATH", "models/piper/en_US-ryan-low.onnx"))
    # Ring-modulation robot-voice effect layered on top of whichever Piper
    # voice is configured (2026-09-24, user picked the 45Hz/60%-mix setting
    # after hearing several options -- see voice/effects.py). On by default;
    # doesn't change which voice model is used, just post-processes its
    # output. G2_VOICE_ROBOT_EFFECT=0 to turn it off.
    # Which robot voice to use: plain | current | dalek | monotone | metal | retro | deep (see voice/effects.py VOICES).
    # Defaults to `metal` (chosen by listening 2026-10-04); G2_VOICE_ROBOT_EFFECT=0 still means plain.
    voice_style: str = field(default_factory=lambda: _env("G2_VOICE_STYLE") or (
        "plain" if _env("G2_VOICE_ROBOT_EFFECT", "1") in ("0", "false", "no") else "metal"))
    voice_robot_effect: bool = field(default_factory=lambda: _env("G2_VOICE_ROBOT_EFFECT", "1") not in ("0", "false", "no"))
    stt_silence_s: float = field(default_factory=lambda: _env_float("G2_STT_SILENCE_S", 0.5))
    # After a reply, keep the mic open this long for a follow-up before requiring
    # the wake word again. Resets on every exchange, so a normal back-and-forth
    # never re-triggers. A large value ~= "stay awake until I say 'go to sleep'".
    # 0 = every turn needs the wake word (most private).
    follow_up_s: float = field(default_factory=lambda: _env_float("G2_FOLLOW_UP_S", 60.0))
    # Voice-loop speech output: auto (piper in --mode voice, mac in text) | mac | piper | print. Use `print`
    # on a Pi with no speaker wired: Piper would spend seconds synthesising audio nobody hears.
    tts_mode: str = field(default_factory=lambda: _env("G2_TTS", "auto"))
    # Warn (log + diagnostics event) when the SD card is this percent full or more.
    disk_warn_pct: float = field(default_factory=lambda: _env_float("G2_DISK_WARN_PCT", 85.0))
    # Claude API connection: keep the pooled HTTPS connection alive this long (the SDK default is 5 s, which
    # is shorter than a human pause between turns, so most turns pay a fresh TCP+TLS handshake), and open it
    # in the background the moment the wake word is heard.
    api_keepalive_s: float = field(default_factory=lambda: _env_float("G2_API_KEEPALIVE_S", 300.0))
    api_warmup: bool = field(default_factory=lambda: _env("G2_API_WARMUP", "1").lower() not in ("0", "false", "off", "no"))
    # Stream Claude's reply: speak each finished sentence and send each skill as soon as it is complete, instead of
    # waiting for the whole reply. 0 = off (the old whole-reply behaviour, for A/B timing).
    stream_replies: bool = field(default_factory=lambda: _env("G2_STREAM", "1").lower() not in ("0", "false", "off", "no"))
    # Which voice stages beep, comma separated from: listening, thinking, heard. `thinking` = a command going to Claude.
    cue_stages: str = field(default_factory=lambda: _env("G2_CUE_STAGES", "thinking"))
    # Buzzer volume sent to the board at start (1-10; 0 = leave it as it is).
    # What acknowledges a command that goes to Claude: short_tone (one short blip through the speaker; default), star_trek_whistle (continuous tone through the Pi speaker; default), buzzer (the old
    # low blip on G2's buzzer) or off. The whistle needs the speaker, i.e. voice mode with spoken replies.
    # Low-battery watch (robot's 2S pack, read with the firmware's `P` command): alert with the star_trek_red_alert siren.
    battery_watch: bool = field(default_factory=lambda: _env("G2_BATTERY_WATCH", "1") not in ("0", "false", "no"))
    battery_low_v: float = field(default_factory=lambda: _env_float("G2_BATTERY_LOW_V", 7.2))   # ~20% of a 2S Li-ion pack at rest
    battery_critical_v: float = field(default_factory=lambda: _env_float("G2_BATTERY_CRITICAL_V", 6.6))
    battery_poll_s: float = field(default_factory=lambda: _env_float("G2_BATTERY_POLL_S", 60.0))
    # The Pi's own battery can't be read, so its charge is estimated from uptime against the measured runtime per charge.
    pi_runtime_log: str = field(default_factory=lambda: os.path.expanduser(_env("G2_PI_RUNTIME_LOG", "~/.local/share/g2/pi_runtime.json")))
    pi_full_runtime_s: float = field(default_factory=lambda: _env_float("G2_PI_FULL_RUNTIME_S", 0.0))   # 0 = use the mean of the logged runs
    # the 80%-of-runtime warning: on, but silent until a timed battery test has measured a runtime (it counts uptime since boot,
    # so a reboot resets it). 0 turns it off.
    pi_battery_watch: bool = field(default_factory=lambda: _env("G2_PI_BATTERY_WATCH", "1") not in ("0", "false", "no"))
    # G2's standing wobble (firmware gyro balance going unstable on a 5 Hz IMU, see gait/stand_guard.py): keep balance off while idle
    # (on only around a firmware gait) and run a guard that turns it off if a wobble starts anyway.
    balance_off_idle: bool = field(default_factory=lambda: _env("G2_BALANCE_OFF_IDLE", "1") not in ("0", "false", "no"))
    stand_guard: bool = field(default_factory=lambda: _env("G2_STAND_GUARD", "1") not in ("0", "false", "no"))
    # Describe what G2 sees: when the user asks, a picture from G2's camera goes to Claude with that message (never saved or kept).
    vision_describe: bool = field(default_factory=lambda: _env("G2_VISION_DESCRIBE", "1") not in ("0", "false", "no"))
    # Sounds that say the camera is in use: a shutter chirp per picture, a rising chirp when continuous capture starts (repeated as a
    # reminder), a falling one when it stops. See voice/camera_sounds.py.
    camera_sounds: bool = field(default_factory=lambda: _env("G2_CAMERA_SOUNDS", "1") not in ("0", "false", "no"))
    camera_peak: float = field(default_factory=lambda: _env_float("G2_CAMERA_PEAK", 0.045))
    camera_reminder_s: float = field(default_factory=lambda: _env_float("G2_CAMERA_REMINDER_S", 60.0))
    # Opt-in: keep every camera picture in this folder (empty = never save, the default). For collecting a test set; delete afterwards.
    vision_save_dir: str = field(default_factory=lambda: os.path.expanduser(_env("G2_VISION_SAVE_DIR", "")))
    # Tidy-up at service start: delete diagnostic session folders and walk logs older than this many days (0 = never).
    tidy_days: float = field(default_factory=lambda: _env_float("G2_TIDY_DAYS", 30.0))
    runs_dir: str = field(default_factory=lambda: os.path.expanduser(_env("G2_RUNS_DIR", "~/g2_runs")))
    # Camera-preview captures (~/g2_cap) are meant to be pulled to the Mac (g2pcam-pull) and then forgotten: cleared at every service start.
    capture_dir: str = field(default_factory=lambda: os.path.expanduser(_env("G2_CAP_DIR", "~/g2_cap")))
    clear_captures: bool = field(default_factory=lambda: _env("G2_CLEAR_CAPTURES", "1") not in ("0", "false", "no"))
    # Per-day Claude API call/token counts, including how often the words-only retry fires (python -m pi_pipeline.voice.usage).
    usage_path: str = field(default_factory=lambda: os.path.expanduser(_env("G2_USAGE_FILE", "~/.local/share/g2/api_usage.json")))
    picture_keep_days: float = field(default_factory=lambda: _env_float("G2_PICTURE_KEEP_DAYS", 7.0))   # saved pictures older than this are deleted
    capture_keep_s: float = field(default_factory=lambda: _env_float("G2_CAPTURE_KEEP_S", 3600.0))      # preview captures touched this recently survive the start-up clear
    # Re-take a look picture in better light when the first is blown out or too dark (moves the camera's exposure target; see vision/snapshot.py).
    vision_exposure_check: bool = field(default_factory=lambda: _env("G2_EXPOSURE_CHECK", "1") not in ("0", "false", "no"))
    # Memory: how many identity-level ("core") facts are always injected, how long sightings are kept, and idle-time consolidation.
    memory_core_max: int = field(default_factory=lambda: _env_int("G2_MEMORY_CORE_MAX", 12))
    observation_days: float = field(default_factory=lambda: _env_float("G2_OBSERVATION_DAYS", 30.0))
    consolidate: bool = field(default_factory=lambda: _env("G2_CONSOLIDATE", "1") not in ("0", "false", "no"))
    consolidate_idle_s: float = field(default_factory=lambda: _env_float("G2_CONSOLIDATE_IDLE_S", 1200.0))
    consolidate_min_exchanges: int = field(default_factory=lambda: _env_int("G2_CONSOLIDATE_MIN_EXCHANGES", 6))
    consolidate_min_interval_s: float = field(default_factory=lambda: _env_float("G2_CONSOLIDATE_MIN_INTERVAL_S", 21600.0))
    # Which memory shaped a reply (python -m pi_pipeline.memory usage): "match" = the code compares each reply with the notes it was given
    # (free, always on); "declare" = also give G2 a memory_used tool to name the notes that mattered (richer, but in a measured test the
    # model skipped speaking more often, so the words-only retry fired on ~3 of 8 question turns: extra API calls); "off" = neither.
    memory_use_log: str = field(default_factory=lambda: _env("G2_MEMORY_USE_LOG", "match").lower())
    # "boot" (default): the Pi-battery warning counts from boot ("you're plugged in" pauses it, "you're unplugged" restarts the count);
    # "manual": it counts only after you say "you're unplugged".
    pi_battery_arm: str = field(default_factory=lambda: _env("G2_PI_BATTERY_ARM", "boot").lower())
    # "Shut down": G2 lies down AND the Pi powers itself off cleanly (sudo shutdown -h now), after a short chance to say "cancel". Only for a
    # clear, short command; anything else keeps the old lie-down-and-go-dormant behaviour. 0 turns the OS shutdown off.
    poweroff_on_shutdown: bool = field(default_factory=lambda: _env("G2_POWEROFF_ON_SHUTDOWN", "1") not in ("0", "false", "no"))
    shutdown_confirm_s: float = field(default_factory=lambda: _env_float("G2_SHUTDOWN_CONFIRM_S", 6.0))
    ack_tone: str = field(default_factory=lambda: _env("G2_ACK_TONE", "short_tone"))
    # loudness of the battery alert sounds (whistle for G2's pack, siren for the Pi's), fraction of full scale: 10% of the 0.45 reference
    alert_peak: float = field(default_factory=lambda: _env_float("G2_ALERT_PEAK", 0.045))
    ack_peak: float = field(default_factory=lambda: _env_float("G2_ACK_PEAK", 0.0225))   # fraction of full scale
    buzzer_volume: int = field(default_factory=lambda: _env_int("G2_BUZZER_VOLUME", 10))
    # Voice-loop buzzer cues: raise every note by this many semitones and make each note this many times longer.
    # Small piezo buzzers are loudest around 2-4 kHz, so higher and longer sounds louder. 0 / 1.0 = the raw chirp melodies.
    buzzer_shift: float = field(default_factory=lambda: _env_float("G2_BUZZER_SHIFT", 0.0))
    buzzer_length: float = field(default_factory=lambda: _env_float("G2_BUZZER_LEN", 1.0))
    # After G2 asks a question, keep listening this many seconds for the answer without the wake word (0 = never).
    question_window_s: float = field(default_factory=lambda: _env_float("G2_QUESTION_WINDOW_S", 8.0))
    # Auto-stop a looping gait (walk/trot/crawl) started by voice after this many seconds. 0 = off.
    max_gait_s: float = field(default_factory=lambda: _env_float("G2_MAX_GAIT_S", 0.0))

    # --- Memory (Phase 9) ---
    memory_enabled: bool = field(default_factory=lambda: _env("G2_MEMORY", "1") not in ("0", "false", "no"))
    # Default is OUTSIDE the repo/synced tree -- G2's memory is personal data and
    # must not ride along in git or a cloud-synced project folder. '~' expands.
    memory_db_path: str = field(default_factory=lambda: os.path.expanduser(
        _env("G2_MEMORY_DB", "~/.local/share/g2/g2_memory.db")))
    memory_max_facts: int = field(default_factory=lambda: _env_int("G2_MEMORY_MAX_FACTS", 30))
    memory_recall_exchanges: int = field(default_factory=lambda: _env_int("G2_MEMORY_RECALL", 3))

    # --- Object recognition gallery (B20 -- behind `features.object_gallery`) ---
    # Same rule as memory_db_path: personal photos of things in the house live
    # OUTSIDE the repo/synced tree, never in git or a cloud-synced folder.
    object_gallery_dir: str = field(default_factory=lambda: os.path.expanduser(
        _env("G2_OBJECT_GALLERY_DIR", "~/.local/share/g2/object_gallery")))
    object_gallery_max_entries: int = field(default_factory=lambda: _env_int("G2_OBJECT_GALLERY_MAX_ENTRIES", 200))
    object_gallery_max_samples: int = field(default_factory=lambda: _env_int("G2_OBJECT_GALLERY_MAX_SAMPLES", 5))
    object_gallery_max_mb: int = field(default_factory=lambda: _env_int("G2_OBJECT_GALLERY_MAX_MB", 200))

    # --- Robot link (used on hardware; ignored by MockActuator) ---
    # /dev/serial0 = "the primary UART", whichever physical one it is. On the Pi
    # Zero 2 W after `dtoverlay=disable-bt` (see setup_pi.sh) that's the stable
    # PL011 (ttyAMA0), not the clock-dependent mini-UART (ttyS0).
    serial_port: str = field(default_factory=lambda: _env("G2_SERIAL_PORT", "/dev/serial0"))
    serial_baud: int = field(default_factory=lambda: _env_int("G2_SERIAL_BAUD", 115200))

    # --- Vision (Phase 8; used on hardware) ---
    vision_serial_port: str = field(default_factory=lambda: _env("VISION_SERIAL_PORT", "/dev/ttyACM0"))
    vision_serial_baud: int = field(default_factory=lambda: _env_int("VISION_SERIAL_BAUD", 921600))
    vision_frame_px: int = field(default_factory=lambda: _env_int("VISION_FRAME_PX", 240))
    # sensor capture option: 0=240x240, 1=480x480, 2=640x480. 1 gives a cleaner
    # downscale to the model input at no serial cost. Boxes then come in that
    # frame; SerialDetectionFeed reads the per-message `resolution`.
    vision_sensor_opt: int = field(default_factory=lambda: _env_int("VISION_SENSOR_OPT", 1))
    # OV5647 auto-exposure lift for dim rooms (0 = off; ~32 helps a lot, ~48 is
    # aggressive). Runtime-only, re-applied on every open. TUNE on the mounted
    # camera under real lighting -- a fixed lift over-exposes bright scenes.
    vision_ae_bump: int = field(default_factory=lambda: _env_int("VISION_AE_BUMP", 32))
    # drop detections scoring below this (0-100). Raise if a model over-
    # fires (e.g. a single-class model trained without negatives). 0 = off.
    vision_min_score: int = field(default_factory=lambda: _env_int("VISION_MIN_SCORE", 0))
    vision_labels: list[str] = field(default_factory=lambda: [
        s.strip() for s in _env("VISION_LABELS").split(",") if s.strip()
    ])  # deployed model's class names, in id order; empty -> "obj<id>"

    def require_api_key(self) -> str:
        """Returns the API key, or raises with setup instructions if unset."""
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env at the "
                "repo root and fill it in."
            )
        return self.anthropic_api_key

    def api_key_expiry_status(self, today: "_dt.date | None" = None) -> tuple[str, str]:
        """(level, message). level: 'ok' | 'warn' | 'expired' | 'unset' | 'malformed'.
        'ok' and 'unset' carry an empty message. Set ANTHROPIC_API_KEY_EXPIRES to
        the console key's expiry date to enable the check."""
        raw = self.api_key_expires
        if not raw:
            return "unset", ""
        try:
            exp = _dt.date.fromisoformat(raw)
        except ValueError:
            return "malformed", (
                f"ANTHROPIC_API_KEY_EXPIRES={raw!r} is not a YYYY-MM-DD date -- "
                "expiry check disabled")
        today = today or _dt.date.today()
        days = (exp - today).days
        if days < 0:
            return "expired", (
                f"ANTHROPIC_API_KEY expired {-days} day(s) ago ({raw}). Create a "
                "new key (Console -> API Keys, G2 workspace), update .env, and "
                "reset ANTHROPIC_API_KEY_EXPIRES.")
        if days <= self.api_key_expiry_warn_days:
            return "warn", (
                f"ANTHROPIC_API_KEY expires in {days} day(s) ({raw}) -- plan to "
                "rotate it (Console -> API Keys, G2 workspace).")
        return "ok", ""


settings = Settings()
