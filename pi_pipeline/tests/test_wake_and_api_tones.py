"""The wake chime (right after the wake word) and the API-call tone: distinct sounds, the stage and the hook fire, nothing real is played or called."""
import numpy as np

from pi_pipeline.voice import api_log, api_tone, short_tone, wake_chime
from pi_pipeline.voice.cues import DEFAULT_STAGES, SpeakerCue


def test_sounds_are_distinct_and_short():
    w, a, s = wake_chime.render(), api_tone.render(), short_tone.render() if hasattr(short_tone, "render") else None
    assert w.dtype == a.dtype == np.int16
    assert 0.2 < len(w) / 48000 < 0.5 and 0.15 < len(a) / 48000 < 0.4
    assert len(w) != len(a)
    assert np.abs(w).max() > 0 and np.abs(a).max() > 0


def test_awake_stage_plays_the_wake_chime_only():
    played = []
    cue = SpeakerCue(stages=DEFAULT_STAGES, player=lambda: played.append(1))
    cue.set("listening"); cue.set("thinking"); cue.set("idle")
    assert played == []
    cue.set("awake")
    assert played == [1]


def test_call_hook_fires_for_create_not_for_models_list():
    class _M:
        def create(self, *a, **k): return type("R", (), {"stop_reason": "end_turn", "usage": None, "content": []})()
    class _L:
        def list(self, *a, **k): return []
    class _C:
        messages, models = _M(), _L()
    seen = []
    api_log.set_call_hook(lambda api, source: seen.append(api))
    try:
        c = api_log.instrument(_C(), "test")
        c.models.list()
        assert seen == []
        c.messages.create(model="m", max_tokens=1, messages=[{"role": "user", "content": "hi"}])
        assert seen == ["messages.create"]
    finally:
        api_log.set_call_hook(None)


def test_shutter_is_louder_than_the_other_signals():
    from pi_pipeline.voice import shutter
    assert np.abs(shutter.render()).max() > 3 * np.abs(api_tone.render()).max()


def test_every_picture_path_clicks(monkeypatch):
    from pi_pipeline.voice import shutter
    clicks = []
    monkeypatch.setattr(shutter, "play", lambda *a, **k: clicks.append(1))
    monkeypatch.setenv("G2_SHUTTER", "on")
    shutter.click()
    assert clicks == [1]
    monkeypatch.setenv("G2_SHUTTER", "off")
    shutter.click()
    assert clicks == [1]



def test_prompt_tones_are_three_distinct_sounds_and_the_cue_plays_each_on_its_stage():
    from pi_pipeline.voice import prompt_tones as pt
    from pi_pipeline.voice.cues import LOW_CUES, SpeakerCue
    b, o, c = pt.render_beep(), pt.render_boop(), pt.render_close()
    assert b.dtype == o.dtype == c.dtype and 0.08 < b.size / 48000 < 0.2 and 0.15 < o.size / 48000 < 0.3 and 0.3 < c.size / 48000 < 0.6
    assert len({b.size, o.size, c.size}) == 3
    assert set(("awake", "captured", "closed")) <= set(LOW_CUES)
    assert len({tuple(LOW_CUES[k]) for k in ("awake", "captured", "closed")}) == 3
    played = []
    cue = SpeakerCue(player=lambda: played.append("p"), stages=("awake", "captured", "closed"))
    for st in ("awake", "listening", "captured", "heard", "closed"):
        cue.set(st)
    assert played == ["p", "p", "p"]                           # only the three stages sound
