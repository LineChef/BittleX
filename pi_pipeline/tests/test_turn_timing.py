from pi_pipeline.voice.timing import TurnTrace, parse, summarize


def test_intervals_from_stamps():
    tr = TurnTrace()
    for name, t in (("speech_end", 10.0), ("transcript", 10.6), ("claude_start", 10.65),
                    ("claude_end", 12.45), ("voice_start", 12.5), ("move_sent", 12.9)):
        tr.stamp(name, t)
    iv = tr.intervals()
    assert iv["stt_wait"] == 0.6 and iv["claude"] == 1.8
    assert iv["total_to_voice"] == 2.5 and iv["total_to_move"] == 2.9


def test_missing_stages_are_skipped_and_first_stamp_wins():
    tr = TurnTrace()
    tr.stamp("transcript", 1.0)
    tr.stamp("transcript", 5.0)           # ignored: the first stamp stands
    tr.stamp("claude_start", 1.5)
    assert tr.intervals() == {"pre_claude": 0.5}


def test_log_lines_round_trip_through_the_summary():
    tr = TurnTrace()
    tr.stamp("speech_end", 0.0); tr.stamp("transcript", 0.5)
    tr.meta["warm"] = True
    text = "08:00:00 g2.loop " + tr.line() + "\nnoise\n"
    turns = parse(text)
    assert turns == [{"stt_wait": 0.5, "warm": True}]
    assert "stt_wait" in summarize(turns) and "1/1" in summarize(turns)
