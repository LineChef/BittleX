import numpy as np

from pi_pipeline.config import Settings
from pi_pipeline.voice import short_tone, star_trek_whistle
from pi_pipeline.voice.cues import SpeakerCue


def test_one_short_tone_at_the_ack_level():
    y = short_tone.render(48000)
    assert 0.10 < len(y) / 48000 < 0.15
    assert abs(np.abs(y).max() / 32767 - star_trek_whistle.DEFAULT_PEAK) < 0.002
    sp = np.abs(np.fft.rfft(y.astype(float), 1 << 16)); fr = np.fft.rfftfreq(1 << 16, 1 / 48000)
    assert abs(fr[np.argmax(sp)] - 880) < 30


def test_the_default_acknowledgement_is_the_short_tone_and_alerts_are_louder():
    s = Settings()
    assert s.ack_tone == "short_tone"
    assert abs(s.ack_peak - 0.0225) < 1e-9 and abs(s.alert_peak - 0.045) < 1e-9


def test_speaker_cue_can_use_either_tone():
    for tone in ("short_tone", "star_trek_whistle"):
        SpeakerCue(tone=tone, stages=("thinking",), player=lambda: None).set("thinking")
