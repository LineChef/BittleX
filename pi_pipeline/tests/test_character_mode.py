import pytest

from pi_pipeline.personality import character_state
from pi_pipeline.personality.personality import Personality
from pi_pipeline.voice.commands import (
    match_local_command, parse_character_command,
)


# ------------------------------------------------------------ command parsing
@pytest.mark.parametrize("text,on,level", [
    ("enable gir mode", True, None),
    ("turn on gir", True, None),
    ("gir mode on", True, None),
    ("go into gir mode please", True, None),
    ("set gir to 70", True, 0.7),
    ("gir mode at 0.9", True, 0.9),
    ("turn gir to full", True, 1.0),
    ("disable gir mode", False, None),
    ("turn off gir", False, None),
    ("gir mode off", False, None),
    ("stop being gir", False, None),
    ("no more gir", False, None),
])
def test_parse_character_command(text, on, level):
    cc = parse_character_command(text)
    assert cc is not None and cc.name == "gir"
    assert cc.on is on
    if level is None:
        assert cc.level is None
    else:
        assert abs(cc.level - level) < 1e-9


@pytest.mark.parametrize("text", [
    "what is gir mode",
    "tell me about the gir character",
    "i saw a gir plushie today",
    "the weather is nice",
])
def test_non_commands_fall_through(text):
    assert parse_character_command(text) is None


def test_match_local_command_routes_character():
    assert match_local_command("enable gir mode") == "character"
    assert match_local_command("what is gir mode") is None
    assert match_local_command("forget that") == "forget"


# ------------------------------------------------------- Personality toggling
def test_with_and_without_character():
    base = Personality.from_spec("curiosity=0.8")
    assert not any(t.name == "gir" for t in base.traits)

    on = base.with_character("gir", 0.5)
    g = [t for t in on.traits if t.name == "gir"]
    assert g and abs(g[0].level - 0.5) < 1e-9
    assert any(t.name == "curiosity" for t in on.traits)      # composed, not replaced

    on2 = on.with_character("gir", 0.9)                       # replace level
    assert [t for t in on2.traits if t.name == "gir"][0].level == 0.9
    assert sum(t.name == "gir" for t in on2.traits) == 1      # no duplicate

    off = on2.without_character("gir")
    assert not any(t.name == "gir" for t in off.traits)
    assert any(t.name == "curiosity" for t in off.traits)


# --------------------------------------------------- runtime state persistence
@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_STATE_DIR", str(tmp_path))
    yield tmp_path


def test_character_state_round_trip(state_dir):
    assert character_state.load() == (None, None)
    character_state.save("gir", 0.6)
    assert character_state.load() == ("gir", 0.6)
    character_state.clear()
    assert character_state.load() == (None, None)


class _S:
    traits_spec = "curiosity=0.8"
    character_spec = ""
    character_level = 0.4


def test_from_settings_runtime_state_beats_env(state_dir):
    s = _S()
    s.character_spec = "gir"          # env default would be gir=0.4
    # no state file -> env wins
    assert [t.level for t in Personality.from_settings(s).traits if t.name == "gir"] == [0.4]
    # a state file -> it wins
    character_state.save("gir", 0.85)
    assert [t.level for t in Personality.from_settings(s).traits if t.name == "gir"] == [0.85]
    # runtime_state=False ignores it
    assert [t.level for t in Personality.from_settings(s, runtime_state=False).traits
            if t.name == "gir"] == [0.4]


def test_from_settings_no_character_at_all(state_dir):
    assert not any(t.name == "gir" for t in Personality.from_settings(_S()).traits)


# ------------------------------------------------------ voice loop integration
class _TTS:
    def __init__(self): self.said = []
    def speak(self, s): self.said.append(s)


class _Conv:
    def __init__(self):
        self._personality = Personality.from_spec("curiosity=0.8")
    @property
    def personality(self): return self._personality
    def set_personality(self, p): self._personality = p


class _Cue:
    def set(self, *_): pass


def _loop(**kw):
    from pi_pipeline.voice.loop import VoiceLoop

    class _Stub:
        def __getattr__(self, n): return lambda *a, **k: None
    return VoiceLoop(wake_word=_Stub(), stt=_Stub(), conversation=kw["conv"],
                     tts=kw["tts"], actuator=_Stub(), cue=_Cue())


def test_loop_enables_and_persists_character(state_dir):
    tts, conv = _TTS(), _Conv()
    vl = _loop(conv=conv, tts=tts)
    vl._handle_character(parse_character_command("set gir to 60"))
    assert any(t.name == "gir" and abs(t.level - 0.6) < 1e-9 for t in conv.personality.traits)
    assert character_state.load() == ("gir", 0.6)
    assert "gir mode on" in " ".join(tts.said).lower()

    vl._handle_character(parse_character_command("turn off gir"))
    assert not any(t.name == "gir" for t in conv.personality.traits)
    assert character_state.load() == (None, None)
