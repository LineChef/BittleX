import json
import types

from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.voice.conversation import Conversation
from pi_pipeline.voice.usage import UsageTracker, summarize

JPEG = b"\xff\xd8\xff\xe0fake\xff\xd9"


def usage(i, o):
    return types.SimpleNamespace(input_tokens=i, output_tokens=o)


def test_tracker_counts_turns_retries_and_tokens_per_day(tmp_path):
    t = UsageTracker(tmp_path / "u.json", today=lambda: "2026-10-05")
    t.record("turn", usage(1000, 50)); t.record("turn", usage(1200, 60)); t.record("retry", usage(1300, 40))
    (day, d), = t.days()
    assert day == "2026-10-05" and d["turns"] == 2 and d["retries"] == 1
    assert d["in_tokens"] == 3500 and d["out_tokens"] == 150 and d["retry_in_tokens"] == 1300
    text = summarize(t)
    assert "33.3%" in text and "2026-10-05" in text                     # 1 retry out of 3 calls


def test_tracker_survives_a_corrupt_file_and_missing_usage(tmp_path):
    p = tmp_path / "u.json"; p.write_text("{nope")
    t = UsageTracker(p, today=lambda: "d")
    t.record("turn", None)
    assert json.loads(p.read_text())["days"]["d"]["turns"] == 1


def test_summary_with_nothing_recorded(tmp_path):
    assert "no API usage" in summarize(UsageTracker(tmp_path / "none.json"))


def test_a_silent_reply_records_one_turn_and_one_retry(cfg, fake_anthropic, tmp_path):
    import dataclasses
    replies = iter([Resp(Block("tool_use", name="remember", id="r1", input={"fact": "x"}), stop_reason="tool_use"),
                    Resp(Block("text", text="I see a desk."))])
    replies_list = list(replies)
    for r, u in zip(replies_list, (usage(900, 20), usage(1000, 30))):
        r.usage = u
    it = iter(replies_list)
    fake_anthropic.set_reply(lambda: next(it))
    c = dataclasses.replace(cfg, usage_path=str(tmp_path / "u.json"))
    Conversation(c).send("what do you see", image=JPEG, image_note="[pic]")
    (day, d), = UsageTracker(tmp_path / "u.json").days()
    assert d["turns"] == 1 and d["retries"] == 1 and d["retry_in_tokens"] == 1000 and d["in_tokens"] == 1900


def test_a_normal_reply_records_no_retry(cfg, fake_anthropic, tmp_path):
    import dataclasses
    r = Resp(Block("text", text="hi")); r.usage = usage(500, 10)
    fake_anthropic.set_reply(r)
    Conversation(dataclasses.replace(cfg, usage_path=str(tmp_path / "u.json"))).send("hello")
    (day, d), = UsageTracker(tmp_path / "u.json").days()
    assert d["turns"] == 1 and d["retries"] == 0
