from pi_pipeline.voice.wake_word import AlwaysAwake, _parse_phrases, make_wake_word


def test_parse_phrases_splits_strips_lowercases():
    assert _parse_phrases("gee two, hey buddy, hey bud") == ["gee two", "hey buddy", "hey bud"]
    assert _parse_phrases("  Gee Two ,  Hey Buddy ") == ["gee two", "hey buddy"]


def test_parse_phrases_drops_empties_and_dedupes():
    assert _parse_phrases("gee two,, gee two ,hey bud") == ["gee two", "hey bud"]
    assert _parse_phrases("") == []


def test_parse_phrases_accepts_a_list_too():
    assert _parse_phrases(["Gee Two", "hey buddy"]) == ["gee two", "hey buddy"]


def test_make_wake_word_mock_mode_ignores_phrase():
    ww = make_wake_word("mock", vosk_model_path="unused", phrase="gee two, hey buddy")
    assert isinstance(ww, AlwaysAwake)
    ww.wait()  # returns immediately, no error
