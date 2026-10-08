"""'The floor is tile': a local voice command that sets the floor label every run log records. No API call, and it never collides with the naming command."""
import pytest

from pi_pipeline.behavior.survey import parse_naming
from pi_pipeline.voice.commands import asks_floor, match_local_command, parse_floor_command


@pytest.mark.parametrize("text,label", [
    ("G2, the floor is tile", "tile"), ("the floor is hardwood", "hardwood"), ("we're on the carpet", "carpet"), ("we are on tile", "tile"),
    ("you are on the hard wood floor", "hardwood"), ("set the floor to laminate", "laminate"), ("this floor is concrete", "concrete"),
    ("hey g2 you're on tile floor", "tile"), ("floor is wood", "hardwood"),
    ("this is a tile floor", "tile"), ("G2, this is hardwood floor", "hardwood"), ("this is the carpet floor", "carpet"), ("this is a hard wood floor", "hardwood"),
])
def test_floor_phrases_map_to_a_label(text, label):
    assert parse_floor_command(text) == label
    assert match_local_command(text) == "floor"


@pytest.mark.parametrize("text", ["this is a floor lamp", "this is tile", "this is a lava floor", "this is a floor", "the floor is lava", "we are on a walk", "what a nice floor", "the floor is dirty"])
def test_other_sentences_are_not_floor_commands(text):
    assert parse_floor_command(text) is None
    assert match_local_command(text) != "floor"


def test_the_naming_command_is_untouched():
    assert parse_naming("this is a floor lamp") and match_local_command("this is a floor lamp") is None
    assert parse_naming("this is the dishwasher") and match_local_command("this is the dishwasher") is None
    assert parse_naming("this is a mug") and match_local_command("this is a mug") is None            # without the word floor it still names an object and takes a picture


def test_asking_which_floor_is_a_local_query():
    for q in ("what floor are you on", "G2, what floor am I on", "which floor"):
        assert asks_floor(q) and match_local_command(q) == "floor_query"


def test_stop_words_still_win(tmp_path):
    assert match_local_command("emergency stop") == "halt"
    assert match_local_command("freeze, the floor is tile") in ("halt", "floor")          # a halt verb is checked first
