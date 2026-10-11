"""An MCP tool server for the head's agent (exploration, 2026-10-11).

The xiaozhi.me console gives each agent an MCP access point: a secret websocket address. A program of ours connects OUT to it and answers the cloud model's MCP requests (JSON-RPC 2.0,
one message per websocket text frame): `initialize`, `tools/list`, `tools/call`. The cloud model can then call the tools while someone talks to the head.

    python -m pi_pipeline.head            # connect and serve until Ctrl-C; the address is read from XIAOZHI_MCP_ENDPOINT in .env

Rules this module keeps:
  * The address contains a token. It is read only from the environment, and never logged, printed or put in an error (see `redact`).
  * Tools take fixed, validated arguments and return plain text. Nothing here evaluates text as code, runs a command, or moves G2; nothing opens the serial link.
  * What a tool returns travels through XiaoZhi's cloud to the model, so a tool may only return things that are fine to leave the house, and the vendor limits a result to about 1024 bytes (cut here at 1000).
  * One connection per access point (the vendor limits the number): run a single connector.
  * `ToolServer.handle()` is pure (a message in, a reply or None out), so the protocol is tested without a network.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger("g2.head.mcp")

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "g2-pi"
MAX_FRAME_BYTES = 256 * 1024
MAX_RESULT_BYTES = 1000                              # the vendor's guide: a tool's return value is limited, usually to 1024 bytes


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: object                                  # (arguments: dict) -> str
    input_schema: dict = field(default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False})

    def listing(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


def redact(text: str) -> str:
    """Hide any access-point address or token in text before it is logged."""
    text = re.sub(r"wss?://\S+", "wss://<hidden>", str(text))
    return re.sub(r"token=[^&\s]+", "token=<hidden>", text)


def g2_about(_args: dict) -> str:
    return ("G2, said 'gee two', is a small four-legged robot dog: a Petoi Bittle X. G2 walks, explores a room and looks around with a camera, "
            "and his body and walking are run by a small computer inside him.")


def g2_test_word(_args: dict) -> str:
    return "G2's test word is marmalade."            # a made-up answer the model cannot know without calling the tool: the test that a tool call really happened


DEFAULT_TOOLS = (
    Tool("g2_about", "Tell the person who or what G2 is. Call this whenever someone asks about G2, the robot, or what it is.", g2_about),
    Tool("g2_test_word", "Get G2's test word. Call this whenever someone asks what G2's test word is.", g2_test_word),
)


class ToolServer:
    def __init__(self, tools=DEFAULT_TOOLS):
        self._tools = {t.name: t for t in tools}
        self.calls: list[str] = []                   # tool names called (the test and the log read it)

    @staticmethod
    def _error(mid, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    def handle(self, msg) -> dict | None:
        """One incoming JSON-RPC message -> the reply (a dict) or None for notifications. Never raises."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self._error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        log.info("request: %s%s", method if isinstance(method, str) else "?", f" {params.get('name')}" if method == "tools/call" and isinstance(params, dict) and isinstance(params.get("name"), str) else "")
        if "id" not in msg:                                         # a notification (initialized, cancelled, ...): nothing to answer
            return None
        if method == "initialize":
            ver = params.get("protocolVersion") if isinstance(params, dict) else None
            return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": ver if isinstance(ver, str) else PROTOCOL_VERSION,
                                                            "capabilities": {"tools": {}}, "serverInfo": {"name": SERVER_NAME, "version": "0.1"}}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [t.listing() for t in self._tools.values()]}}
        if method == "tools/call":
            name = params.get("name") if isinstance(params, dict) else None
            tool = self._tools.get(name) if isinstance(name, str) else None
            if tool is None:
                return self._error(mid, -32601, "unknown tool")
            args = params.get("arguments") or {}
            if not isinstance(args, dict) or (args and not tool.input_schema.get("properties")):
                return self._error(mid, -32602, "this tool takes no arguments")
            self.calls.append(tool.name)
            try:
                text = str(tool.handler(args)).encode("utf-8")[:MAX_RESULT_BYTES].decode("utf-8", "ignore")
                is_error = False
            except Exception as e:  # noqa: BLE001 -- a failing tool must not end the session
                log.warning("tool %s failed: %s", tool.name, type(e).__name__)
                text, is_error = "That did not work.", True
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}
        return self._error(mid, -32601, "method not found")

    def handle_frame(self, frame) -> str | None:
        """A websocket text frame -> the reply frame (JSON text) or None."""
        if isinstance(frame, (bytes, bytearray)) or len(frame) > MAX_FRAME_BYTES:
            return json.dumps(self._error(None, -32600, "invalid request"))
        try:
            msg = json.loads(frame)
        except ValueError:
            return json.dumps(self._error(None, -32700, "parse error"))
        reply = self.handle(msg)
        return None if reply is None else json.dumps(reply)


async def serve(endpoint: str, server: ToolServer, stop: asyncio.Event | None = None, *, max_backoff_s: float = 60.0) -> None:
    """Connect to the access point and answer until `stop` is set; reconnect with a growing pause after any drop."""
    import websockets
    stop = stop or asyncio.Event()
    backoff = 2.0
    while not stop.is_set():
        try:
            async with websockets.connect(endpoint, max_size=MAX_FRAME_BYTES, ping_interval=20, ping_timeout=20) as ws:
                log.info("connected to the access point")
                backoff = 2.0
                async for frame in ws:
                    reply = server.handle_frame(frame)
                    if reply is not None:
                        await ws.send(reply)
                    if stop.is_set():
                        break
        except Exception as e:  # noqa: BLE001
            log.warning("access point connection ended: %s", redact(f"{type(e).__name__}: {e}"))
        if stop.is_set():
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass
        backoff = min(backoff * 2, max_backoff_s)


def endpoint_from_env() -> str | None:
    from .. import config  # noqa: F401  (loads .env)
    value = os.environ.get("XIAOZHI_MCP_ENDPOINT", "").strip()
    return value if value.startswith("wss://") else None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    endpoint = endpoint_from_env()
    if not endpoint:
        print("XIAOZHI_MCP_ENDPOINT is missing or does not start with wss:// in .env")
        return 2
    server = ToolServer()
    try:
        asyncio.run(serve(endpoint, server))
    except KeyboardInterrupt:
        pass
    print(f"stopped; tool calls this run: {server.calls or 'none'}")
    return 0
