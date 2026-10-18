

def test_a_recap_becomes_an_observation_for_the_memory():
    from pi_pipeline.reflection.recap import observation_from_recap
    cap, labels = observation_from_recap({"seen": {"chair": 3, "dog": 1}, "rooms": {"kitchen": 4, "hall": 1}, "events": {"wall.hit": 2}})
    assert cap == "While exploring I saw a chair (at 3 stops), a dog; I was mostly in the kitchen, also the hall; I bumped into something twice."
    assert labels == "chair,dog"
    assert observation_from_recap({"seen": {}, "events": {"wall.steer": 3}}) == ("", "")
    assert observation_from_recap({}) == ("", "")


def test_where_and_exploring_questions_recall_what_he_saw():
    from pi_pipeline.memory.memory import _PAST_SIGHT_RE
    for q in ("where's the chair?", "Where is my shoe", "what did you find while exploring?", "how was exploring"):
        assert _PAST_SIGHT_RE.search(q), q
    assert not _PAST_SIGHT_RE.search("tell me a joke")
