"""pi_pipeline/head/mcp_tools.py: the MCP messages, the redaction of the access-point address, and a real websocket round trip against a local server."""
import asyncio
import json

import pytest

from pi_pipeline.head.mcp_tools import DEFAULT_TOOLS, ToolServer, Tool, redact, endpoint_from_env


def _req(method, mid=1, **params):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}


def test_initialize_lists_the_tools_and_answers_ping():
    s = ToolServer()
    init = s.handle(_req("initialize", protocolVersion="2025-03-26", capabilities={}))
    assert init["result"]["protocolVersion"] == "2025-03-26" and init["result"]["capabilities"] == {"tools": {}} and init["id"] == 1
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None            # a notification gets no answer
    tools = s.handle(_req("tools/list", 2))["result"]["tools"]
    assert [t["name"] for t in tools] == ["g2_about", "g2_test_word"] and tools[0]["inputSchema"]["type"] == "object" and "description" in tools[0]
    assert s.handle(_req("ping", 3))["result"] == {}


def test_a_tool_call_returns_text_and_is_recorded_and_bad_calls_are_clean_errors():
    s = ToolServer()
    ok = s.handle(_req("tools/call", 4, name="g2_about", arguments={}))
    assert ok["result"]["isError"] is False and "gee two" in ok["result"]["content"][0]["text"] and s.calls == ["g2_about"]
    assert s.handle(_req("tools/call", 5, name="rm_rf", arguments={}))["error"]["code"] == -32601
    assert s.handle(_req("tools/call", 6, name="g2_about", arguments={"x": "1"}))["error"]["code"] == -32602         # this tool takes no arguments
    assert s.handle(_req("nonsense", 7))["error"]["code"] == -32601
    assert s.handle({"id": 8, "method": "ping"})["error"]["code"] == -32600 and s.handle("text")["error"]["code"] == -32600
    assert s.calls == ["g2_about"]
    assert "marmalade" in s.handle(_req("tools/call", 9, name="g2_test_word", arguments={}))["result"]["content"][0]["text"]


def test_a_long_result_is_cut_to_the_vendors_size_limit_without_breaking_a_character():
    s = ToolServer([Tool("long", "x", lambda _a: "é" * 900)])                                  # 1800 bytes
    text = s.handle(_req("tools/call", 1, name="long", arguments={}))["result"]["content"][0]["text"]
    assert len(text.encode("utf-8")) <= 1000 and text == "é" * 500


def test_a_failing_tool_is_an_error_result_not_a_crash():
    def boom(_a):
        raise RuntimeError("secret detail")
    s = ToolServer([Tool("bad", "x", boom)])
    r = s.handle(_req("tools/call", 1, name="bad", arguments={}))
    assert r["result"]["isError"] is True and "secret" not in json.dumps(r)


def test_frames_are_parsed_safely():
    s = ToolServer()
    assert json.loads(s.handle_frame("not json"))["error"]["code"] == -32700
    assert json.loads(s.handle_frame(b"\x00"))["error"]["code"] == -32600
    assert json.loads(s.handle_frame("x" * 300_000))["error"]["code"] == -32600
    assert s.handle_frame(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None


def test_the_address_and_token_are_hidden_in_anything_logged():
    ep = "wss://api.example.me/mcp/?token=abc.DEF-123_xyz"
    shown = redact(f"InvalidURI: {ep} refused; retry token=abc.DEF-123_xyz")
    assert "abc" not in shown and "api.example" not in shown and "<hidden>" in shown


def test_the_endpoint_is_read_from_the_environment_and_must_be_secure(monkeypatch):
    monkeypatch.delenv("XIAOZHI_MCP_ENDPOINT", raising=False)
    assert endpoint_from_env() is None
    monkeypatch.setenv("XIAOZHI_MCP_ENDPOINT", "ws://plain.example/x")
    assert endpoint_from_env() is None
    monkeypatch.setenv("XIAOZHI_MCP_ENDPOINT", " wss://ok.example/x?token=t ")
    assert endpoint_from_env() == "wss://ok.example/x?token=t"


def test_a_real_websocket_round_trip_serves_the_cloud_side_and_reconnects():
    websockets = pytest.importorskip("websockets")
    from pi_pipeline.head.mcp_tools import serve

    async def scenario():
        got, replies = [], []
        connections = {"n": 0}

        async def cloud(ws):
            connections["n"] += 1
            if connections["n"] == 1:
                await ws.close()                                         # the first connection drops: the connector must come back
                return
            for i, m in enumerate([_req("initialize", 1, protocolVersion="2024-11-05"), {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                   _req("tools/list", 2), _req("tools/call", 3, name="g2_about", arguments={})]):
                await ws.send(json.dumps(m))
                if "id" in m:
                    replies.append(json.loads(await ws.recv()))
            got.append(True)

        async with websockets.serve(cloud, "127.0.0.1", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            server, stop = ToolServer(), asyncio.Event()
            task = asyncio.create_task(serve(f"ws://127.0.0.1:{port}", server, stop, max_backoff_s=0.1))
            for _ in range(100):
                if got:
                    break
                await asyncio.sleep(0.1)
            stop.set()
            await asyncio.wait_for(task, 5)
        return replies, server, connections["n"]

    replies, server, n = asyncio.run(scenario())
    assert n >= 2 and [r["id"] for r in replies] == [1, 2, 3] and replies[1]["result"]["tools"][0]["name"] == "g2_about" and server.calls == ["g2_about"]


def _store(tmp_path):
    from pi_pipeline.memory.store import Store
    st = Store(str(tmp_path / "m.db"))
    st.add_fact("Sam has a cat named Biscuit.", importance=4)
    st.add_fact("The kitchen floor is hardwood.", importance=2)
    st.add_fact("Sam lives here.", importance=5, core=True)
    st.add_observation("a red ball under the table")
    st.log_exchange("secret chat line", "reply", [])
    return st


def test_recall_returns_facts_and_sightings_scrubs_names_and_never_transcripts(tmp_path):
    from pi_pipeline.head.recall import recall_text
    st = _store(tmp_path)
    out = recall_text(st, "", names=["Sam"])
    assert "Sam" not in out and "[name] lives here" in out and "red ball" in out and "secret chat" not in out
    cat = recall_text(st, "cat", names=["Sam"])
    assert "Biscuit" in cat and "hardwood" not in cat
    assert "nothing saved" in recall_text(st, "dragons")
    assert len(recall_text(st, "", limit_bytes=40).encode()) <= 40


def test_recall_does_not_touch_the_fact_recency_and_is_off_unless_enabled(tmp_path, monkeypatch):
    from pi_pipeline.head import recall
    st = _store(tmp_path)
    before = [r["last_recalled"] for r in st.list_facts()]
    recall.recall_text(st, "cat")
    assert [r["last_recalled"] for r in st.list_facts()] == before
    monkeypatch.delenv("G2_HEAD_RECALL", raising=False)
    assert not recall.enabled()
    monkeypatch.setenv("G2_HEAD_RECALL", "1")
    assert recall.enabled()


def test_recall_tool_is_called_through_the_server_with_a_topic(tmp_path):
    from pi_pipeline.head.recall import make_tool
    s = ToolServer([make_tool(lambda: _store(tmp_path), ["Sam"])])
    assert s.handle(_req("tools/list", 1))["result"]["tools"][0]["inputSchema"]["properties"]["topic"]
    r = s.handle(_req("tools/call", 2, name="g2_recall", arguments={"topic": "cat"}))
    assert r["result"]["isError"] is False and "Biscuit" in r["result"]["content"][0]["text"] and s.calls == ["g2_recall"]
    assert s.handle(_req("tools/call", 3, name="g2_recall", arguments={"topic": 5}))["result"]["isError"] is True
