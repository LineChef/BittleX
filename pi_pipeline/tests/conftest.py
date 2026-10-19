"""Shared test fixtures. No network, no audio, no API key."""
from __future__ import annotations

import types

import pytest

from pi_pipeline.config import Settings


@pytest.fixture(autouse=True)
def _isolate_api_log(tmp_path, monkeypatch):
    """The Claude API call log goes to a per-test tmp file, never the developer's ~/.local/share/g2."""
    monkeypatch.setenv("G2_API_LOG", str(tmp_path / "api_calls.jsonl"))


@pytest.fixture(autouse=True)
def _no_speaker_sounds(monkeypatch):
    """Tests never play a sound on the developer's speakers (the exploration fanfare came out of the Mac during a test run, 2026-10-09)."""
    monkeypatch.setenv("G2_SPEAKER_SOUNDS", "0")


@pytest.fixture(autouse=True)
def _isolate_diag_logs(tmp_path, monkeypatch):
    """Any test that exercises a CLI `main()` (doctor, check_serial, voice, ...)
    may start a real `diag` session -- redirect it to a per-test tmp dir so the
    suite never writes to the developer's actual ~/g2_logs."""
    monkeypatch.setenv("G2_LOG_DIR", str(tmp_path / "g2_logs"))


@pytest.fixture
def cfg(tmp_path):
    """A Settings pointed at a temp DB, with a fake API key so Conversation builds."""
    s = Settings()
    over = {
        "anthropic_api_key": "sk-test",
        "memory_db_path": str(tmp_path / "mem.db"),
        "memory_max_facts": 5,
        "memory_recall_exchanges": 2,
        "history_turns": 2,
        "claude_max_tokens": 100,
        "usage_path": "",                 # tests never write usage counts into the real home folder
    }
    for k, v in over.items():
        object.__setattr__(s, k, v)
    return s


class Block:
    """Stand-in for an anthropic content block."""

    def __init__(self, type, **kw):
        self.type = type
        self.text = kw.get("text", "")
        self.name = kw.get("name", "")
        self.id = kw.get("id", "")
        self.input = kw.get("input", None)
        for k, v in kw.items():                   # any other field a test passes (e.g. a thinking block's signature)
            if k not in ("text", "name", "id", "input"):
                setattr(self, k, v)


class Resp:
    def __init__(self, *blocks, stop_reason="end_turn"):
        self.content = list(blocks)
        self.stop_reason = stop_reason


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Patch anthropic.Anthropic; `set_reply(Resp(...))` controls the next call.
    Returns a recorder with `.calls` (kwargs of each messages.create call)."""
    import anthropic

    rec = types.SimpleNamespace(calls=[], _next=Resp(Block("text", text="ok")))

    def _create(**kw):
        # snapshot messages: conv._history is mutated (assistant reply appended)
        # right after this returns, so a live reference would mislead assertions
        rec.calls.append({**kw, "messages": [{**m, "content": list(m["content"]) if isinstance(m["content"], list) else m["content"]}
                                                   for m in kw["messages"]]})
        return rec._next() if callable(rec._next) else rec._next

    fake = types.SimpleNamespace(messages=types.SimpleNamespace(create=_create))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: fake)
    rec.set_reply = lambda r: setattr(rec, "_next", r)
    return rec


@pytest.fixture(autouse=True)
def _no_shutter_sound(monkeypatch):
    """Tests never play the picture click through the dev machine's speaker (tests that check it patch `shutter.play`)."""
    monkeypatch.setenv("G2_SHUTTER", "off")


@pytest.fixture(autouse=True)
def _no_autolog(monkeypatch, tmp_path_factory):
    """Tests never write automatic run logs into the real ~/g2_runs/auto (the autolog tests turn it on and point it at a temp folder)."""
    monkeypatch.setenv("G2_AUTOLOG", "off")
    monkeypatch.setenv("G2_STAND_RAMP_S", "off")    # the stand-up ramp adds ~0.8 s of setup pause that timing tests count; its own tests turn it back on
    monkeypatch.setenv("G2_TRANSITION_RAMP_S", "off")    # the same for the eased transition into a skill (link/transitions.py)


@pytest.fixture(autouse=True)
def _one_frame_per_survey_picture(monkeypatch):
    """Survey pictures take extra frames and keep the sharpest on the Pi; tests that count camera calls take one (the best-of-three test sets it itself)."""
    from pi_pipeline.vision.exploration_pictures import ExplorationPictureSaver
    monkeypatch.setattr(ExplorationPictureSaver, "_extra_frames", 0)


@pytest.fixture(autouse=True)
def _no_wake_log(monkeypatch):
    """Tests never write into the real wake-trigger log (its own tests point it at a temp file)."""
    monkeypatch.setenv("G2_WAKE_LOG", "off")


@pytest.fixture(autouse=True)
def _no_body_state_or_speech_cache(monkeypatch):
    """Tests never write G2's real body-state file or speech cache (their own tests point them at temp paths)."""
    monkeypatch.setenv("G2_BODY_STATE", "off")
    monkeypatch.setenv("G2_SPEECH_CACHE", "off")


@pytest.fixture(autouse=True)
def _no_floor_question(monkeypatch):
    """The voice loop asks which floor he is on before an exploration (voice/loop.py `_ask_floor`); tests turn it on themselves."""
    monkeypatch.setenv("G2_FLOOR_PROMPT_S", "0")


@pytest.fixture(autouse=True)
def _no_detection_log(monkeypatch):
    """Tests never write detection logs into the real ~/g2_runs/detections."""
    monkeypatch.setenv("G2_DETECTION_LOG", "off")


@pytest.fixture(autouse=True)
def _no_attachment(monkeypatch, tmp_path):
    """Tests run with attachment none unless they set one: the machine's G2_ATTACHMENT and ~/.local/share/g2/attachment.json are ignored."""
    monkeypatch.delenv("G2_ATTACHMENT", raising=False)
    monkeypatch.setenv("G2_ATTACHMENT_FILE", str(tmp_path / "attachment.json"))
