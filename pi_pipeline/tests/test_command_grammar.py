from pi_pipeline.voice.commands import grammar_phrases, pick_command_hypothesis


def test_grammar_includes_shutdown_and_halt_phrases():
    p = grammar_phrases()
    assert "shut down" in p and "emergency stop" in p and "gee two shut down" in p


def test_grammar_command_overrides_a_misheard_short_transcript():
    assert pick_command_hypothesis("she to shut dawn", "gee two shut down") == "gee two shut down"
    assert pick_command_hypothesis("today", "shut down") == "shut down"


def test_grammar_never_overrides_long_sentences_or_unknowns():
    assert pick_command_hypothesis("i would like you to tell me why a computer might shut down at night", "shut down") \
        == "i would like you to tell me why a computer might shut down at night"
    assert pick_command_hypothesis("hello there", "[unk] shut down") == "hello there"
    assert pick_command_hypothesis("hello there", "") == "hello there"
    assert pick_command_hypothesis("hello there", "gee two") == "hello there"


def test_full_transcript_that_is_already_a_command_is_kept():
    assert pick_command_hypothesis("power off", "shut down") == "power off"
