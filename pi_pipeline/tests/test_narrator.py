from pi_pipeline.behavior.driver import Effect, EffectKind
from pi_pipeline.behavior.narrator import Narrator, attach, line_for


def test_reasons_map_to_short_lines():
    assert line_for("investigate dog") == ("investigate", "Let me look at this dog.")
    assert line_for("look at cat")[1] == "I noticed a cat."
    assert line_for("follow person")[1] == "I see someone." and line_for("what was that?")[0] == "sound"
    assert line_for("approach novelty")[0] == "approach"
    assert line_for("look-around")[1] == "Looking around."
    assert line_for("breathing") is None and line_for("") is None


def _n(**kw):
    t = [0.0]
    n = Narrator(lambda s: None, clock=lambda: t[0], threaded=False, **kw)
    return n, t


def test_rate_limited_between_lines_and_for_repeats():
    n, t = _n(min_gap_s=8, repeat_s=40)
    scan = [Effect(EffectKind.HEAD, "pan_sweep", "look-around")]
    sound = [Effect(EffectKind.HEAD, 0.4, "toward a sound")]
    assert n.narrate(scan) == "Looking around."
    t[0] = 3
    assert n.narrate(sound) is None                        # too soon after the last line
    t[0] = 10
    assert n.narrate(scan) is None                         # same kind inside the repeat window
    assert n.narrate(sound) == "I heard something."
    t[0] = 60
    assert n.narrate(scan) == "Looking around."


def test_chirps_and_diag_are_never_narrated_and_disabled_is_silent():
    n, _ = _n()
    assert n.narrate([Effect(EffectKind.CHIRP, "happy", "look at dog")]) is None
    n.enabled = False
    assert n.narrate([Effect(EffectKind.HEAD, 0, "look-around")]) is None


def test_attach_narrates_after_acting_and_a_failing_narrator_does_not_break_dispatch():
    class B:
        def dispatch(self, x):
            return ["ok"]

    b = B()
    n, _ = _n()
    attach(b, n)
    assert b.dispatch([Effect(EffectKind.STOP, None, "investigate dog")]) == ["ok"] and n.said == ["Let me look at this dog."]
    n.narrate = lambda e: 1 / 0
    assert b.dispatch([]) == ["ok"]


def test_a_bonded_persons_name_is_never_spoken():
    assert line_for("approach alice", private=["Alice"])[1] == "I'm heading over to someone."
    assert line_for("look at alice", private=["alice"])[1] == "I noticed someone."
