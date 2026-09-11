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


# ------------------------------------------------------------------ rebuff (B6)
import pytest
from pi_pipeline.voice.commands import looks_like_rebuff


@pytest.mark.parametrize("text", [
    "leave me alone", "G2, stop it", "be quiet please", "shut up",
    "okay that's enough", "knock it off", "stop talking", "you're annoying",
])
def test_rebuff_phrases_match(text):
    assert looks_like_rebuff(text)


@pytest.mark.parametrize("text", [
    "what's the weather", "tell me a story about a quiet forest",
    "can you stop the timer at noon", "I left my keys somewhere",
])
def test_ordinary_sentences_are_not_rebuffs(text):
    assert not looks_like_rebuff(text)


# ------------------------------------------------- explore / shutdown commands
from pi_pipeline.voice.commands import match_local_command as _mlc


def test_explore_and_unexplore_phrases():
    for p in ("go ahead and look around", "exploration mode", "look around",
              "go explore", "wander around"):
        assert _mlc(p) == "explore", p
    for p in ("that's enough", "stop exploring", "come back", "stop looking around"):
        assert _mlc(p) == "unexplore", p


def test_shutdown_is_its_own_command_not_a_halt():
    for p in ("shut down", "shutdown", "power down", "go dormant", "G2 shut down"):
        assert _mlc(p) == "shutdown", p
    # and the emergency phrases still halt
    assert _mlc("emergency stop") == "halt"
    assert _mlc("freeze") == "halt"
