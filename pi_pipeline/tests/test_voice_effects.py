

def _speechlike(rate=16000, secs=1.0):
    import numpy as np
    t = np.arange(int(rate * secs)) / rate
    return (9000 * np.sin(2 * np.pi * 150 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.int16)


def test_every_named_voice_returns_int16_audio_of_similar_length():
    import numpy as np
    from pi_pipeline.voice import effects
    a = _speechlike()
    for name, fn in effects.VOICES.items():
        out = fn(a, 16000)
        assert out.dtype == np.int16 and len(out) > 0, name
        assert abs(len(out) - len(a)) < 0.35 * len(a), name        # pitch_shift lengthens a little; nothing explodes
        assert np.abs(out).max() > 0, name


def test_monotone_makes_the_output_repeat_at_the_chosen_pitch():
    import numpy as np
    from pi_pipeline.voice import effects
    rng = np.random.default_rng(1)
    noise = (rng.standard_normal(16000) * 4000).astype(np.int16)
    out = effects.monotone(noise, 16000, 100.0).astype(np.float64)
    out -= out.mean()

    def ac(lag):
        return float(np.dot(out[:-lag], out[lag:]) / np.dot(out, out))

    assert ac(160) > 0.5 and abs(ac(80)) < 0.1            # repeats every 100 Hz period (160 samples), not in between


def test_helpers_keep_silence_silent_and_handle_empty_input():
    import numpy as np
    from pi_pipeline.voice import effects
    z = np.zeros(800, dtype=np.int16)
    for fn in (lambda a: effects.monotone(a, 16000), lambda a: effects.comb(a, 16000), effects.bitcrush,
               lambda a: effects.pitch_shift(a, -3), effects.normalize):
        assert np.abs(fn(z)).max() == 0
        assert len(fn(np.zeros(0, dtype=np.int16))) == 0


def test_comb_block_form_matches_the_plain_recursion():
    import numpy as np
    from pi_pipeline.voice import effects
    x = (np.random.default_rng(3).standard_normal(3000) * 3000).astype(np.int16)
    d = int(16000 * 5.0 / 1000)
    y = np.zeros(len(x))
    for i in range(len(x)):
        y[i] = x[i] + (0.5 * y[i - d] if i >= d else 0.0)
    expected = np.clip(0.4 * x + 0.6 * y, -32768, 32767).astype(np.int16)
    assert np.abs(effects.comb(x, 16000, 5.0, 0.5, 0.6).astype(int) - expected.astype(int)).max() <= 1


def test_apply_style_plain_unknown_and_metal():
    import numpy as np
    from pi_pipeline.voice import effects
    a = _speechlike()
    assert effects.apply_style("plain", a, 16000) is a
    assert effects.apply_style("no-such-voice", a, 16000) is a           # unknown name: left alone
    m = effects.apply_style("metal", a, 16000)
    assert m.dtype == np.int16 and not np.array_equal(m, a)
    assert abs(int(np.abs(m).max()) - int(0.65 * 0.95 * 32767)) < 50       # levelled to the global volume, 65% of max (user, 2026-11-02)


def test_speech_plays_at_the_global_volume_whatever_level_it_was_made_or_cached_at(monkeypatch):
    import types
    import numpy as np
    from pi_pipeline import sound_levels as lv
    from pi_pipeline.voice import tts
    played = []
    t = object.__new__(tts.PiperTTS)                                   # no Piper model needed: only the playback path
    t._sd = types.SimpleNamespace(play=lambda a, r: played.append(a), wait=lambda: None)
    loud = (np.sin(np.linspace(0, 60, 4000)) * 32000).astype(np.int16)   # a line cached at almost full scale
    t.play(("hi", loud, 16000))
    assert abs(int(np.abs(played[-1]).max()) - int(lv.peak() * 32767)) <= 1
    monkeypatch.setenv("G2_VOLUME", "30")
    t.play(("hi", loud // 10, 16000))                                 # a quiet one comes up to the volume too
    assert abs(int(np.abs(played[-1]).max()) - int(0.30 * 0.95 * 32767)) <= 1
