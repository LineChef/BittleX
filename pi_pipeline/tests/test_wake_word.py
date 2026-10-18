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


def test_phrase_confidence_is_the_lowest_word_confidence_of_the_phrase():
    import json
    from pi_pipeline.voice.wake_word import phrase_confidence
    r = json.dumps({"text": "hey gee two", "result": [{"word": "hey", "conf": 0.4}, {"word": "gee", "conf": 0.93}, {"word": "two", "conf": 0.71}]})
    assert phrase_confidence(r, "gee two") == 0.71
    assert phrase_confidence(r, "hey buddy") is None and phrase_confidence("not json", "gee two") is None


def test_a_low_confidence_wake_word_is_ignored_only_when_the_gate_is_on(monkeypatch, caplog):
    """2026-10-18: 4 of 7 wake triggers were people talking nearby; the partial result fires, then a forced final decode gives each word's confidence."""
    import json
    import logging
    from pi_pipeline.tests.test_wake_handover import _Rec, _wake
    confs = iter([0.35, 0.92])
    made = []

    class Rec(_Rec):
        def __init__(self, *a):
            super().__init__(*a)
            made.append(self)
            self.c = next(confs, 0.92)

        def SetWords(self, on):
            self.words = on

        def FinalResult(self):
            return json.dumps({"text": "gee two", "result": [{"word": "gee", "conf": self.c}, {"word": "two", "conf": 0.99}]})

    monkeypatch.setenv("G2_WAKE_MIN_CONF", "0.7")
    w, _ = _wake()
    w._Recognizer = Rec
    with caplog.at_level(logging.INFO, logger="g2.wake"):
        w.wait()
    text = caplog.text
    assert "wake word ignored ('gee two', confidence 0.35 < 0.70)" in text and "confidence=0.92" in text
    assert len(made) == 2 and made[0].words is True                # a fresh recogniser after the rejected one, words switched on
    monkeypatch.setenv("G2_WAKE_MIN_CONF", "0")
    confs = iter([0.2])
    made.clear()
    w2, _ = _wake()
    w2._Recognizer = Rec
    w2.wait()
    assert len(made) == 1                                         # the gate is off by default: the first hit wakes him


def test_words_before_and_the_gate_setting(monkeypatch):
    from pi_pipeline.voice.wake_word import max_words_before, words_before
    assert words_before("gee two", "gee two") == 0 and words_before("[unk] [unk] gee two", "gee two") == 2
    monkeypatch.delenv("G2_WAKE_MAX_BEFORE", raising=False)
    assert max_words_before() is None
    monkeypatch.setenv("G2_WAKE_MAX_BEFORE", "1")
    assert max_words_before() == 1
    monkeypatch.setenv("G2_WAKE_MAX_BEFORE", "x")
    assert max_words_before() is None


def test_phrase_buried_in_talk_is_ignored_when_the_cap_is_set(monkeypatch):
    import json
    from pi_pipeline.tests.test_wake_handover import _Rec, _wake
    texts = iter(["[unk] [unk] [unk] gee two", "gee two"])
    made = []

    class Rec(_Rec):
        def __init__(self, *a):
            super().__init__(*a)
            made.append(self)
            self.t = next(texts, "gee two")

        def PartialResult(self):
            return json.dumps({"partial": self.t if self.n >= 2 else ""})
    monkeypatch.setenv("G2_WAKE_MAX_BEFORE", "1")
    monkeypatch.setenv("G2_WAKE_LOG", "off")
    w, _ = _wake()
    w._Recognizer = Rec
    w.wait()
    assert len(made) == 2                      # the first (buried) hit was dropped and a fresh recogniser made


def test_suggest_min_conf_needs_data_and_separation():
    from pi_pipeline.voice.wake_log import suggest_min_conf
    assert suggest_min_conf([0.9, 0.95], [0.3, 0.4, 0.5]) is None             # too few real ones
    s = suggest_min_conf([0.8, 0.9, 0.95], [0.3, 0.4, 0.5])
    assert s is not None and 0.5 < s[0] <= 0.8 and s[1] == 3 and s[2] == 0
    assert suggest_min_conf([0.3, 0.4, 0.5], [0.8, 0.9, 0.95]) is None        # false ones are MORE confident: no threshold helps
