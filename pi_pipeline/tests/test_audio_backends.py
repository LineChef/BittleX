"""Offline validation for the Piper / Vosk backends.

These SKIP until `pip install -r pi_pipeline/requirements-audio.txt` + the model
downloads (`bash pi_pipeline/fetch_models.sh`). No microphone / speaker needed --
Piper synthesises to a WAV, Vosk transcribes that WAV back.
"""
import wave
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_PIPER = _REPO / "models" / "piper" / "en_US-ryan-low.onnx"
_VOSK = _REPO / "models" / "vosk" / "am" / "final.mdl"

piper = pytest.importorskip("piper", reason="piper-tts not installed (requirements-audio.txt)")
vosk = pytest.importorskip("vosk", reason="vosk not installed (requirements-audio.txt)")


@pytest.mark.skipif(not _PIPER.exists(), reason="run pi_pipeline/fetch_models.sh")
def test_piper_synthesises_a_wav(tmp_path):
    from pi_pipeline.voice.tts import PiperTTS

    tts = PiperTTS(str(_PIPER))
    out = tmp_path / "hi.wav"
    rate, n = tts.synth_to_wav("Hello, I am G2.", out)
    assert out.exists() and n > 0 and rate in (16000, 22050)
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        assert w.getnframes() == n


@pytest.mark.skipif(not (_PIPER.exists() and _VOSK.exists()),
                    reason="run pi_pipeline/fetch_models.sh")
def test_round_trip_piper_then_vosk(tmp_path):
    from pi_pipeline.voice.stt import VoskSTT
    from pi_pipeline.voice.tts import PiperTTS

    phrase = "the quick brown fox jumps over the lazy dog"
    wav = tmp_path / "phrase.wav"
    PiperTTS(str(_PIPER)).synth_to_wav(phrase, wav)
    heard = VoskSTT.transcribe_wav(str(_VOSK.parent.parent), str(wav)).lower()
    # a small model won't be perfect; require most content words back
    hits = sum(w in heard for w in ("quick", "brown", "fox", "lazy", "dog"))
    assert hits >= 3, f"vosk heard {heard!r}"
