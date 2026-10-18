"""The speech cache and the narrator's late-line drop (speech lag, 2026-10-18)."""
import numpy as np

from pi_pipeline.behavior.narrator import Narrator, fixed_lines
from pi_pipeline.voice import speech_cache


def test_store_then_load_round_trips_and_the_key_includes_voice_and_style(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_SPEECH_CACHE", str(tmp_path))
    a = np.arange(10, dtype=np.int16)
    assert speech_cache.load("hello", "v.onnx:metal", 22050) is None
    speech_cache.store("hello", "v.onnx:metal", 22050, a)
    audio, rate = speech_cache.load("hello", "v.onnx:metal", 22050)
    assert rate == 22050 and (audio == a).all()
    assert speech_cache.load("hello", "v.onnx:plain", 22050) is None            # another style is another voice
    assert speech_cache.load("hello", "v.onnx:metal", 16000) is None


def test_the_cache_can_be_turned_off_and_skips_long_text(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_SPEECH_CACHE", "off")
    speech_cache.store("hi", "t", 1, np.zeros(3, dtype=np.int16))
    assert speech_cache.load("hi", "t", 1) is None
    monkeypatch.setenv("G2_SPEECH_CACHE", str(tmp_path))
    speech_cache.store("x" * 500, "t", 1, np.zeros(3, dtype=np.int16))
    assert list(tmp_path.glob("*.npy")) == []


def test_a_damaged_file_is_a_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_SPEECH_CACHE", str(tmp_path))
    speech_cache.store("a", "t", 1, np.zeros(3, dtype=np.int16))
    for f in tmp_path.glob("*.npy"):
        f.write_bytes(b"junk")
    assert speech_cache.load("a", "t", 1) is None


def test_prune_keeps_the_newest(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_SPEECH_CACHE", str(tmp_path))
    monkeypatch.setattr(speech_cache, "MAX_FILES", 3)
    import os
    for i in range(5):
        speech_cache.store(f"t{i}", "t", 1, np.zeros(2, dtype=np.int16))
        for f in tmp_path.glob("*.npy"):
            os.utime(f, (1000 + i, 1000 + i)) if f.stat().st_mtime > 2_000 else None
    assert len(list(tmp_path.glob("*.npy"))) <= 3


def test_prewarm_makes_only_what_is_missing():
    made = []

    class T:
        have = {"a"}

        def is_cached(self, t):
            return t in self.have

        def prepare(self, t):
            made.append(t)
    assert speech_cache.prewarm(T(), ["a", "b", "c"]) == 2 and made == ["b", "c"]


def test_fixed_lines_cover_the_wall_lines():
    ls = fixed_lines()
    assert "Exploring." in ls and "I see a wall about 12 inches ahead. Turning left." in ls
    assert not any("{x}" in t for t in ls)


def test_a_line_that_took_too_long_to_make_is_dropped_but_a_prompt_one_is_played():
    t = [0.0]
    played = []

    def prepare(text):
        t[0] += 9.0 if text == "slow" else 1.0
        return text
    n = Narrator(lambda s: None, clock=lambda: t[0], threaded=False, prepare=prepare, play=played.append)
    n._say_timed(0.0, "slow")
    assert played == []
    t[0] = 100.0
    n._say_timed(100.0, "quick")
    assert played == ["quick"]
