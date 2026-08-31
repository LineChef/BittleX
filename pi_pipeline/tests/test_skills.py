import pytest

from pi_pipeline.voice import skills


def test_catalogue_maps_to_k_prefixed_serial():
    assert skills.serial_command("walk_forward") == "kwkF"
    assert skills.serial_command("sit") == "ksit"
    assert skills.serial_command("wave") == "khi"


def test_every_skill_has_a_valid_command():
    for name in skills.SKILLS:
        cmd = skills.serial_command(name)
        assert cmd.startswith("k") and len(cmd) > 1


def test_unknown_skill_is_not_valid():
    assert not skills.is_valid("backflip")
    assert skills.is_valid("sit")


def test_blocked_tokens_refused():
    skills.SKILLS["_danger"] = skills.Skill("c", "calibrate", False)
    try:
        with pytest.raises(ValueError):
            skills.serial_command("_danger")
    finally:
        del skills.SKILLS["_danger"]


def test_catalogue_for_prompt_lists_names():
    text = skills.catalogue_for_prompt()
    assert "walk_forward" in text and "sit" in text
