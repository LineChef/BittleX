import os
import time

from pi_pipeline.memory.store import Store, similarity
from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.util.tidy import clear_folder
from pi_pipeline.voice.conversation import Conversation

JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"


def sequence(fake_anthropic, *replies):
    it = iter(replies)
    fake_anthropic.set_reply(lambda: next(it))


def remember_only(fact="I look like a small robot."):
    return Resp(Block("tool_use", name="remember", id="r1", input={"fact": fact}), stop_reason="tool_use")


def says(text):
    return Resp(Block("text", text=text))


# ---- never silent

def test_a_tool_only_reply_gets_one_words_only_retry_with_the_picture_and_the_tool_ack(cfg, fake_anthropic):
    sequence(fake_anthropic, remember_only(), says("I see a desk."))
    conv = Conversation(cfg)
    turn = conv.send("what do you see", image=JPEG, image_note="[pic]")
    assert turn.speech == "I see a desk." and turn.facts == ["I look like a small robot."]
    assert len(fake_anthropic.calls) == 2
    second = fake_anthropic.calls[1]
    assert second["tool_choice"] == {"type": "none"}
    msgs = second["messages"]
    assert any(b.get("type") == "image" for m in msgs if isinstance(m["content"], list) for b in m["content"] if isinstance(b, dict))
    last = msgs[-1]["content"]
    assert any(b.get("type") == "tool_result" and b["tool_use_id"] == "r1" for b in last)
    assert any("nothing out loud" in b.get("text", "") for b in last)
    # nothing leaks into the stored history: no picture, and the conversation alternates user / assistant
    assert not any(b.get("type") == "image" for m in conv._history if isinstance(m["content"], list) for b in m["content"]
                   if isinstance(b, dict))
    assert [m["role"] for m in conv._history] == ["user", "assistant", "user", "assistant"]
    assert conv._pending_tool_results == []


def test_no_retry_when_the_reply_has_speech_or_a_move_answered_it(cfg, fake_anthropic):
    sequence(fake_anthropic, says("hello"))
    Conversation(cfg).send("hi")
    assert len(fake_anthropic.calls) == 1
    sequence(fake_anthropic, Resp(Block("tool_use", name="perform_skill", id="s1", input={"skill": "sit"}), stop_reason="tool_use"))
    fake_anthropic.calls.clear()
    turn = Conversation(cfg).send("sit down")
    assert turn.actions == ["sit"] and len(fake_anthropic.calls) == 1


def test_a_picture_turn_that_only_moved_is_still_retried_for_words(cfg, fake_anthropic):
    sequence(fake_anthropic, Resp(Block("tool_use", name="perform_skill", id="s1", input={"skill": "check_around"}),
                                  stop_reason="tool_use"), says("I see a lamp."))
    turn = Conversation(cfg).send("what do you see", image=JPEG, image_note="[pic]")
    assert turn.speech == "I see a lamp." and turn.actions == ["check_around"] and len(fake_anthropic.calls) == 2


def test_the_retry_happens_at_most_once(cfg, fake_anthropic):
    sequence(fake_anthropic, remember_only(), remember_only("another"), says("never reached"))
    turn = Conversation(cfg).send("what do you see", image=JPEG, image_note="[pic]")
    assert len(fake_anthropic.calls) == 2 and turn.speech == ""


def test_a_failed_retry_keeps_the_first_reply_and_its_tool_acks(cfg, fake_anthropic):
    def replies():
        yield remember_only()
        raise RuntimeError("network down")
    it = replies()
    fake_anthropic.set_reply(lambda: next(it))
    conv = Conversation(cfg)
    turn = conv.send("what do you see", image=JPEG, image_note="[pic]")      # must not raise
    assert turn.speech == "" and turn.facts == ["I look like a small robot."]
    assert conv._history[-1]["role"] == "assistant"
    assert [b["tool_use_id"] for b in conv._pending_tool_results] == ["r1"]


# ---- memory facts

def test_similarity_separates_rewordings_from_different_facts():
    assert similarity("They have a cat named Biscuit.", "They have a dog named Biscuit.") < 0.85
    assert similarity("They like strong black coffee.", "They like black coffee, strong.") >= 0.85


def test_near_duplicate_facts_are_skipped_but_different_ones_are_kept(tmp_path):
    st = Store(str(tmp_path / "m.db"))
    assert st.add_fact("They like strong black coffee.")
    assert not st.add_fact("They like black coffee, strong.")
    assert st.add_fact("They have a cat named Biscuit.")
    assert st.add_fact("They have a dog named Biscuit.")
    assert len(st.list_facts()) == 3


def test_g2s_self_description_is_one_slot_and_the_newest_wins(tmp_path):
    st = Store(str(tmp_path / "m.db"))
    st.add_fact("I look like a small white robot with a little blue light.")
    st.add_fact("I look like a small robot with a white body and a label on the front.")
    st.add_fact("I look like a small white robot with dark wires fanning out from a circuit board.")
    st.add_fact("Their name is Sam.")
    facts = [r["fact"] for r in st.list_facts()]
    assert sorted(facts) == ["I look like a small white robot with dark wires fanning out from a circuit board.", "Their name is Sam."]


# ---- preview captures are always cleared

def test_clear_folder_removes_everything_except_what_is_still_being_written(tmp_path):
    old = tmp_path / "session_1"; old.mkdir(); (old / "a.jpg").write_text("x")
    t = time.time() - 3600; os.utime(old, (t, t))
    old_file = tmp_path / "b.jpg"; old_file.write_text("x"); os.utime(old_file, (t, t))
    fresh = tmp_path / "session_2"; fresh.mkdir()                       # modified just now: a session in progress
    (tmp_path / ".keep").write_text("x"); os.utime(tmp_path / ".keep", (t, t))
    link = tmp_path / "link"; link.symlink_to(old_file)
    removed = clear_folder(tmp_path)
    assert sorted(removed) == ["b.jpg", "session_1"]
    assert fresh.exists() and (tmp_path / ".keep").exists() and link.is_symlink() is True


def test_clear_folder_on_a_missing_folder_is_a_no_op(tmp_path):
    assert clear_folder(tmp_path / "nope") == []
