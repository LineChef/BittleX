"""api_log: every Claude API call is logged (start + done/error), with fakes only: these tests never touch the network or the real API."""
import json
import types

import pytest

from pi_pipeline.voice import api_log


def lines(path):
    return [json.loads(l) for l in open(path).read().splitlines()]


class FakeStreamCtx:
    def __init__(self, fail=False):
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return "final"


def fake_client(fail=False):
    def create(**kw):
        if fail:
            raise TimeoutError("slow")
        return types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=1200, output_tokens=40, cache_read_input_tokens=1000), stop_reason="end_turn")
    return types.SimpleNamespace(messages=types.SimpleNamespace(create=create, stream=lambda **kw: FakeStreamCtx()),
                                 models=types.SimpleNamespace(list=lambda **kw: ["m"]))


def test_create_stream_and_warmup_are_each_logged(tmp_path, monkeypatch):
    p = tmp_path / "calls.jsonl"
    monkeypatch.setenv("G2_API_LOG", str(p))
    c = api_log.instrument(fake_client(), "voice")
    c.models.list(limit=1)
    r = c.messages.create(model="m1", max_tokens=300, messages=[{"role": "user", "content": [{"type": "image"}, {"type": "text"}]}], tools=[{}])
    with c.messages.stream(model="m1", max_tokens=300, messages=[{"role": "user", "content": "hi"}]) as s:
        assert s.get_final_message() == "final"                      # the SDK object behind the wrapper still works
    assert r.stop_reason == "end_turn"
    ev = lines(p)
    assert [e["event"] for e in ev] == ["client", "start", "done", "start", "done", "start", "done"]
    assert ev[1]["api"] == "models.list" and ev[1]["source"] == "voice"
    assert ev[3]["api"] == "messages.create" and ev[3]["has_image"] is True and ev[3]["model"] == "m1" and ev[3]["tools"] == 1
    assert ev[4]["input_tokens"] == 1200 and ev[4]["output_tokens"] == 40 and ev[4]["stop_reason"] == "end_turn"
    assert ev[5]["api"] == "messages.stream" and ev[6]["api"] == "messages.stream"
    assert ev[3]["id"] == ev[4]["id"] and ev[3]["caller"].endswith("test_create_stream_and_warmup_are_each_logged")


def test_failed_call_is_logged_and_still_raises(tmp_path, monkeypatch):
    p = tmp_path / "calls.jsonl"
    monkeypatch.setenv("G2_API_LOG", str(p))
    c = api_log.instrument(fake_client(fail=True), "consolidate")
    with pytest.raises(TimeoutError):
        c.messages.create(model="m", max_tokens=5, messages=[])
    assert [e["event"] for e in lines(p)][-2:] == ["start", "error"] and lines(p)[-1]["error"] == "TimeoutError"


def test_off_writes_nothing_and_instrument_is_idempotent(tmp_path, monkeypatch):
    p = tmp_path / "calls.jsonl"
    monkeypatch.setenv("G2_API_LOG", "off")
    c = api_log.instrument(api_log.instrument(fake_client(), "voice"), "voice")
    c.messages.create(model="m", max_tokens=5, messages=[])
    assert not p.exists()
    monkeypatch.setenv("G2_API_LOG", str(p))
    c.messages.create(model="m", max_tokens=5, messages=[])
    assert [e["event"] for e in lines(p)] == ["start", "done"]       # wrapped once, not twice


def test_rotates_at_the_size_cap(tmp_path, monkeypatch):
    p = tmp_path / "calls.jsonl"
    monkeypatch.setenv("G2_API_LOG", str(p))
    monkeypatch.setattr(api_log, "_MAX_BYTES", 200)
    for _ in range(8):
        api_log.log_event("start", "voice", api="messages.create", model="x" * 40)
    assert (tmp_path / "calls.jsonl.1").exists() and p.exists()
