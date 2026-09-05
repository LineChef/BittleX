import pytest

from pi_pipeline.voice.commands import match_local_command


@pytest.mark.parametrize("text", [
    "forget that",
    "Forget that.",
    "forget that please",
    "hey G2, forget that",
    "okay G2 forget that",
    "scratch that",
    "don't remember that",
    "forget what I just said",
    "forget this conversation",
    "forget that last part",          # trailing cruft after the phrase
])
def test_forget_variants(text):
    assert match_local_command(text) == "forget"


@pytest.mark.parametrize("text", [
    "go to sleep",
    "Go to sleep, G2.",
    "hey G2 go to sleep now",
])
def test_sleep_variants(text):
    assert match_local_command(text) == "sleep"


@pytest.mark.parametrize("text", [
    "",
    "   ",
    "what's the weather",
    "I always forget things",
    "can you forget how to walk",
    "let's go for a walk",
    "tell me a story about going to sleep",
    "do you ever sleep",
    "I need to forget my ex",
])
def test_no_false_positives(text):
    assert match_local_command(text) is None
