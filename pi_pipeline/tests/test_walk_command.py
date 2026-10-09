"""'G2, walk for ten seconds' is a local command (2026-10-09): parsed on the Pi and sent straight to the walk, no Claude call."""
import types

import pytest

from pi_pipeline.voice.commands import WALK_DEFAULT_S, match_local_command, parse_walk_command
from pi_pipeline.voice.loop import VoiceLoop


@pytest.mark.parametrize("text,secs", [
    ("walk for ten seconds", 10), ("G2, walk for 10 seconds", 10), ("gee two walk forward for twenty five seconds", 25),
    ("walk forward for two seconds", 2), ("walk for a minute", 60), ("walk for half a minute", 30), ("walk 15 seconds", 15),
    ("start walking for about five seconds", 5), ("walk forward", WALK_DEFAULT_S), ("walk", WALK_DEFAULT_S), ("please walk ahead for 3 secs", 3),
    ("walk for two minutes", 120),
])
def test_walk_phrases(text, secs):
    assert parse_walk_command(text) == secs
    assert match_local_command(text) == "walk"


@pytest.mark.parametrize("text", ["walk to me", "walk backward", "walk the dog", "how far can you walk", "do you like to walk", "walk for a while",
                                  "dont walk", "walk over to the kitchen"])
def test_not_a_local_walk(text):
    assert match_local_command(text) != "walk"


def test_walk_to_me_is_still_come_here():
    assert match_local_command("walk to me") == "come"


def test_the_loop_walks_without_calling_claude():
    heard, said, acts, claude = ["walk for twelve seconds", ""], [], [], []
    lp = VoiceLoop(wake_word=types.SimpleNamespace(wait=lambda: None), stt=types.SimpleNamespace(listen=lambda timeout_s=None: heard.pop(0) if heard else ""),
                   conversation=types.SimpleNamespace(send=lambda *a, **k: claude.append(a), set_mood_hint=lambda h: None, set_narration_hint=lambda h: None),
                   tts=types.SimpleNamespace(speak=said.append),
                   actuator=types.SimpleNamespace(perform=lambda skill, seconds=None: acts.append((skill, seconds)), stop=lambda: None),
                   cue=types.SimpleNamespace(set=lambda s: None), follow_up_s=0.0, on_event=lambda **e: None)
    lp._one_turn()
    assert acts == [("walk_forward", 12.0)]
    assert claude == []
    assert any("Walking for 12 seconds" in s for s in said)
