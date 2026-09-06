import pytest

from pi_pipeline.personality.bonds import (
    NEW_PERSON_CLOSENESS, Bond, Bonds, Disposition, parse_bonds,
)


def test_parse_full_spec():
    bonds = parse_bonds(
        "self:1.0:affectionate; sam:0.7:playful:person; rex:0.4:wary:pet"
    )
    by = {b.label: b for b in bonds}
    assert set(by) == {"self", "sam", "rex"}
    assert by["self"].disposition is Disposition.AFFECTIONATE
    assert by["self"].closeness == 1.0
    assert by["rex"].kind == "pet" and by["rex"].disposition is Disposition.WARY
    assert by["sam"].kind == "person"


@pytest.mark.parametrize("spec", ["", "   ", ";;", None])
def test_parse_empty(spec):
    assert parse_bonds(spec) == []


def test_parse_is_tolerant():
    # missing closeness + disposition, bad disposition, out-of-range closeness,
    # duplicate name (last wins)
    bonds = {b.label: b for b in parse_bonds(
        "a; b:9:zzz; c:-1:curious; a:0.3:fearful"
    )}
    assert bonds["a"].disposition is Disposition.FEARFUL   # last wins
    assert bonds["b"].disposition is Disposition.NEUTRAL   # "zzz" -> neutral
    assert bonds["b"].closeness == 1.0                     # 9 clamped
    assert bonds["c"].closeness == 0.0                     # -1 clamped


def test_disposition_approach_bias_ordering():
    order = [Disposition.AFFECTIONATE, Disposition.PLAYFUL, Disposition.CURIOUS,
             Disposition.NEUTRAL, Disposition.WARY, Disposition.FEARFUL]
    biases = [d.approach_bias for d in order]
    assert biases == sorted(biases, reverse=True)
    assert biases[0] == 1.0 and biases[-1] == -1.0
    assert Disposition.FEARFUL.avoids_on_sight
    assert not Disposition.WARY.avoids_on_sight


def test_lookup_known_and_case_insensitive():
    b = Bonds.from_spec("Sam:0.8:playful")
    assert b.get("sam") is b.get("SAM")
    assert b.disposition_for("sAm") is Disposition.PLAYFUL
    assert b.closeness_for("sam") == 0.8
    assert "sam" in b and len(b) == 1


def test_unknown_person_defaults_to_curious():
    b = Bonds.from_spec("sam:0.8:playful")
    assert b.disposition_for("person") is Disposition.CURIOUS
    assert b.closeness_for("person") == NEW_PERSON_CLOSENESS
    assert b.disposition_for("face") is Disposition.CURIOUS


def test_unknown_nonperson_defaults_to_neutral():
    b = Bonds.from_spec("sam:0.8:playful")
    assert b.disposition_for("mug") is Disposition.NEUTRAL
    assert b.disposition_for("cat") is Disposition.NEUTRAL   # generic animal, not a person
    assert b.closeness_for("mug") == 0.0


def test_seek_bias_scales_with_closeness_for_warm_but_not_cold():
    warm_close = Bond("a", Disposition.AFFECTIONATE, closeness=1.0)
    warm_far = Bond("b", Disposition.AFFECTIONATE, closeness=0.0)
    assert warm_close.seek_bias > warm_far.seek_bias > 0

    fearful_close = Bond("c", Disposition.FEARFUL, closeness=1.0)
    fearful_far = Bond("d", Disposition.FEARFUL, closeness=0.0)
    assert fearful_close.seek_bias == fearful_far.seek_bias == -1.0


def test_note_interaction_drifts_known_bond():
    b = Bonds.from_spec("sam:0.5:playful")
    start = b.closeness_for("sam")
    for _ in range(10):
        b.note_interaction("sam", valence=1.0)
    assert b.closeness_for("sam") > start
    for _ in range(50):
        b.note_interaction("sam", valence=-1.0)
    assert b.closeness_for("sam") < 0.1               # driven toward 0, clamped
    assert 0.0 <= b.closeness_for("sam") <= 1.0

    b.reset_drift()
    assert b.closeness_for("sam") == 0.5              # back to seed


def test_note_interaction_noop_for_unknown():
    b = Bonds.from_spec("sam:0.5:playful")
    b.note_interaction("person", valence=1.0)         # no crash
    b.note_interaction("stranger", valence=-1.0)
    assert b.closeness_for("person") == NEW_PERSON_CLOSENESS  # unchanged


def test_from_settings_reads_bonds_spec():
    import types
    s = types.SimpleNamespace(bonds_spec="self:1.0:affectionate")
    b = Bonds.from_settings(s)
    assert b.disposition_for("self") is Disposition.AFFECTIONATE
