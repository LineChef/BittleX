import array

from pi_pipeline.voice import mic_gain


def _pcm(vals):
    return array.array("h", vals).tobytes()


def test_offset_removed_and_quiet_speech_amplified():
    quiet = [-900 + (30 if i % 2 else -30) for i in range(4000)]      # offset -900, +-30 of signal
    out = array.array("h")
    out.frombytes(mic_gain.boost(_pcm(quiet), 20.0))
    assert abs(sum(out) / len(out)) < 5                                # offset gone
    assert 500 < max(abs(x) for x in out) <= 700                       # 30 * 20


def test_a_loud_block_is_limited_not_clipped():
    loud = [(-900 + (20000 if i % 2 else -20000)) for i in range(4000)]
    out = array.array("h")
    out.frombytes(mic_gain.boost(_pcm(loud), 20.0))
    assert max(abs(x) for x in out) <= 30001                           # scaled to fit


def test_gain_one_is_off_and_silence_is_safe():
    d = _pcm([5] * 100)
    assert mic_gain.boost(d, 1.0) == d
    assert mic_gain.boost(_pcm([7] * 100), 20.0) == _pcm([0] * 100)
