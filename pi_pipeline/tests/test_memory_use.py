import dataclasses
import types

from pi_pipeline.memory.memory import Memory
from pi_pipeline.memory.use_log import format_report, overlap_used, parse_tags
from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.voice.conversation import Conversation


def mem(cfg, tmp_path, **over):
    over.setdefault("memory_use_log", "declare")                      # most of these tests are about the tagged, declared signal
    return Memory(dataclasses.replace(cfg, memory_db_path=str(tmp_path / "m.db"), **over))


def turn(speech, used=()):
    return types.SimpleNamespace(speech=speech, actions=[], facts=[], fact_details=[], memory_used=list(used))


# ---- the matching heuristic

def test_a_reply_that_echoes_a_note_matches_it_and_an_unrelated_one_does_not():
    notes = {1: "The dog is called Biscuit.", 2: "They like strong black coffee.", 3: "Their name is Sam."}
    assert overlap_used("Is Biscuit your dog?", notes) == {1}                          # 2 shared words, 2 of the note's 3
    assert overlap_used("Want me to fetch you a coffee, Sam?", notes) == set()          # one shared word each: not enough
    assert overlap_used("You like your coffee strong and black, don't you?", notes) == {2}
    assert overlap_used("", notes) == set() and overlap_used("hello there", {}) == set()


def test_tags_g2_names_are_parsed_and_junk_is_ignored():
    assert parse_tags(["#12", "s3", " #4 ", "S7"]) == ({12, 4}, {3, 7})
    assert parse_tags(["12", "fact", "#x", None, ""]) == (set(), set())
    assert parse_tags(None) == (set(), set())


# ---- tagging and counting

def test_recall_tags_every_note_and_remembers_what_it_injected(cfg, tmp_path):
    m = mem(cfg, tmp_path)
    m.store.add_fact("The dog is called Biscuit.", importance=5, core=True)
    m.store.add_fact("They like jazz.")
    m.record_observation("I saw a lamp.", "")
    ctx = m.recall("what did you see earlier")
    assert "[#1] The dog is called Biscuit." in ctx and "[#2] They like jazz." in ctx and "[s1]" in ctx
    assert set(m._last_injected["facts"]) == {1, 2} and set(m._last_injected["sights"]) == {1}


def test_a_turn_updates_the_counters_for_declared_and_matched_use(cfg, tmp_path):
    m = mem(cfg, tmp_path)
    m.store.add_fact("The dog is called Biscuit.", importance=5, core=True)
    m.store.add_fact("They like jazz.")
    m.recall("hello")
    m.record("hello", turn("How is Biscuit the dog today?", used=["#2", "#99"]))         # #2 declared; #1 echoed; #99 was never injected
    rows = {r["id"]: r for r in m.store.fact_use_rows()}
    assert (rows[1]["injected"], rows[1]["declared"], rows[1]["matched"]) == (1, 0, 1)
    assert (rows[2]["injected"], rows[2]["declared"], rows[2]["matched"]) == (1, 1, 0)
    assert rows[1]["last_used"] and rows[2]["last_used"]
    assert m.store.get_meta("use_turns") == "1" and m.store.get_meta("use_turns_declared") == "1"
    assert m.store.get_meta("use_turns_matched") == "1" and m.store.get_meta("use_turns_any") == "1"
    m.recall("hi")
    m.record("hi", turn("Hello there!"))                                                # nothing used this time
    rows = {r["id"]: r for r in m.store.fact_use_rows()}
    assert rows[1]["injected"] == 2 and rows[1]["matched"] == 1 and m.store.get_meta("use_turns") == "2"
    assert m.store.get_meta("use_turns_any") == "1"


def test_a_turn_with_no_recall_or_nothing_injected_is_not_counted(cfg, tmp_path):
    m = mem(cfg, tmp_path)
    m.record("hello", turn("hi"))                                                       # record without a recall
    m.recall("hello")                                                                    # nothing stored: nothing injected
    m.record("hello", turn("hi"))
    assert m.store.get_meta("use_turns", "0") == "0"
    assert m._last_injected is None


def test_sightings_are_counted_separately(cfg, tmp_path):
    m = mem(cfg, tmp_path)
    m.store.add_fact("They like jazz.")
    m.record_observation("I saw a bright lamp on the desk.", "")
    m.recall("what did you see earlier")
    m.record("what did you see earlier", turn("Earlier I saw a bright lamp on the desk.", used=["s1"]))
    assert m.store.get_meta("sight_injected") == "1" and m.store.get_meta("sight_declared") == "1"
    assert m.store.get_meta("sight_matched") == "1"


# ---- the tool

def test_memory_used_is_a_tool_with_a_standing_instruction_and_never_changes_the_speech(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(Block("text", text="Biscuit sounds lovely."),
                                  Block("tool_use", name="memory_used", id="m1", input={"notes": ["#1", "s2"]})))
    conv = Conversation(dataclasses.replace(cfg, memory_use_log="declare"))
    t = conv.send("tell me about my dog")
    call = fake_anthropic.calls[-1]
    assert any(x["name"] == "memory_used" for x in call["tools"]) and "never say them aloud" in call["system"]
    assert t.speech == "Biscuit sounds lovely." and t.memory_used == ["#1", "s2"]
    assert conv._pending_tool_results[0]["tool_use_id"] == "m1" and conv._pending_tool_results[0]["content"] == "noted"


def test_a_reply_that_is_only_a_memory_note_still_gets_the_words_only_retry(cfg, fake_anthropic):
    replies = iter([Resp(Block("tool_use", name="memory_used", id="m1", input={"notes": ["#1"]}), stop_reason="tool_use"),
                    Resp(Block("text", text="Your dog is called Biscuit."))])
    fake_anthropic.set_reply(lambda: next(replies))
    t = Conversation(dataclasses.replace(cfg, memory_use_log="declare")).send("what is my dog called")
    assert t.speech == "Your dog is called Biscuit." and t.memory_used == ["#1"] and len(fake_anthropic.calls) == 2


# ---- the report

def test_the_report_shows_rates_per_fact_and_flags_never_used_facts(cfg, tmp_path):
    m = mem(cfg, tmp_path)
    m.store.add_fact("The dog is called Biscuit.", importance=5, core=True)
    m.store.add_fact("They like jazz.")
    assert "no turns" in format_report(m.store)
    for i in range(20):
        m.recall("hello")
        m.record("hello", turn("How is Biscuit the dog?"))
    text = format_report(m.store)
    assert "20 turn(s)" in text and "(100%)" in text and "#1" in text
    assert "never used" in text and "#2" in text and "#1," not in text.split("never used")[1]       # the jazz fact never mattered; the dog fact did


# ---- the default costs nothing: no tags, no tool, no standing note; "off" records nothing

def test_by_default_g2_gets_no_tags_no_tool_and_no_extra_instruction(cfg, fake_anthropic, tmp_path):
    fake_anthropic.set_reply(Resp(Block("text", text="ok")))
    Conversation(cfg).send("hi")
    call = fake_anthropic.calls[-1]
    assert not any(t["name"] == "memory_used" for t in call["tools"]) and "never say them aloud" not in call["system"]
    m = mem(cfg, tmp_path, memory_use_log="match")
    m.store.add_fact("The dog is called Biscuit.", importance=5, core=True)
    ctx = m.recall("hello")
    assert "[#" not in ctx and "- The dog is called Biscuit." in ctx
    m.record("hello", turn("How is Biscuit the dog?"))                  # the reply-matching signal still works
    assert m.store.fact_use_rows()[0]["matched"] == 1 and m.store.fact_use_rows()[0]["declared"] == 0


def test_off_records_nothing(cfg, tmp_path):
    m = mem(cfg, tmp_path, memory_use_log="off")
    m.store.add_fact("The dog is called Biscuit.", importance=5, core=True)
    m.recall("hello"); m.record("hello", turn("How is Biscuit the dog?"))
    assert m.store.get_meta("use_turns", "0") == "0"
