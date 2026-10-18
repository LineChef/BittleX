"""voice/wake_log.py: every wake trigger and its outcome, for counting false triggers."""
from pi_pipeline.voice import wake_log


def test_triggers_and_outcomes_pair_up_and_the_summary_counts_false_ones(tmp_path, monkeypatch):
    path = tmp_path / "wake.jsonl"
    monkeypatch.setenv("G2_WAKE_LOG", str(path))
    wake_log.record_trigger("gee two", "gee two", level=732, confidence=0.97, since_own_sound_s=None)
    wake_log.record_outcome("walk forward", "command", mic_peak=30000)
    wake_log.record_trigger("gee two", "gee two", level=138, confidence=0.41, since_own_sound_s=12.0)
    wake_log.record_outcome("over", "request")                      # junk that went to Claude: looks false
    wake_log.record_trigger("gee two", "gee two", level=179, confidence=0.38, since_own_sound_s=None)
    wake_log.record_outcome("", "empty")
    wake_log.record_trigger("hey buddy", "hey buddy", level=200, confidence=0.2, since_own_sound_s=None, ignored=True)   # the gate ignored it: no outcome follows
    rows = wake_log.read(1.0)
    assert len(rows) == 7 and rows[1]["words"] == 2
    ps = wake_log.pairs(rows)
    assert [wake_log.looks_false(o) for _t, o in ps] == [False, True, True]
    text = wake_log.summary(1.0)
    assert "4 (1 ignored by the confidence gate)" in text and "looked real: 1; looked false: 2" in text and "median 0.41" in text


def test_the_log_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_WAKE_LOG", "off")
    wake_log.record_trigger("gee two", "gee two", level=1, confidence=1.0, since_own_sound_s=None)
    assert wake_log.read(1.0) == [] and "no wake triggers" in wake_log.summary(1.0)
