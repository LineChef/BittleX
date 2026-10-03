"""Swappable LLM backends for the conversation layer.

`Conversation` talks to Claude through the Anthropic SDK by default. This module adds a second, *fast* backend that speaks the
OpenAI-style `/chat/completions` protocol (so it works with free or cheap hosted models and with local servers), plus a
rule-based router that decides which backend answers a turn. Modes (`G2_LLM_MODE`):

- `claude` (default): Claude only. Nothing here is used.
- `fast`: the fast backend only; no Anthropic key needed.
- `routed`: the fast backend answers casual turns; a turn goes to Claude when `needs_claude()` says so, or when the fast backend fails.

History stays in Anthropic content-block shape whichever backend answered. The fast backend's replies are `LLMBlock`s, which carry the
same attributes (`type`, `text`, `id`, `name`, `input`) as the SDK's blocks, so the rest of `Conversation` is unchanged.
No network happens at import; `httpx` (already a dependency of `anthropic`) is imported only when a request is made.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("g2.llm")

# Turns that go to Claude in routed mode. Deliberately conservative: anything personal, anything that needs G2's memory, vision or
# diagnostics, and anything that asks for reasoning. Override with G2_ROUTE_ESCALATE_PATTERN.
DEFAULT_ESCALATE_PATTERN = (
    r"\b(remember|forget|my|mine|our|i am|i'm|we are|we're|i have|i've|who is|what do you see|what can you see|look at|"
    r"why did|what happened|are you ok(ay)?|status|explain|how (do|does|did|would|can)|step by step|plan|compare|"
    r"difference between|calculate|write|translate|summari[sz]e)\b"
)


@dataclass
class LLMBlock:
    """A content block shaped like the Anthropic SDK's (`text` or `tool_use`)."""
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict | None = None

    def to_dict(self) -> dict:
        if self.type == "tool_use":
            return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input or {}}
        return {"type": "text", "text": self.text}


@dataclass
class LLMResponse:
    content: list[Any] = field(default_factory=list)
    stop_reason: str = ""


class LLMError(RuntimeError):
    """A fast-backend call failed. `kind` is 'auth', 'rate', 'billing' or 'transient'."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


# ---------------------------------------------------------------- routing
def needs_claude(text: str, memory_context: str | None, *, sees_memory: bool, max_words: int,
                 pattern: str = DEFAULT_ESCALATE_PATTERN) -> str | None:
    """Why this turn should go to Claude, or None if the fast backend may answer it."""
    if memory_context and not sees_memory:
        return "memory context (kept off the fast backend)"
    if len(text.split()) > max_words:
        return f"long request (> {max_words} words)"
    m = re.search(pattern or DEFAULT_ESCALATE_PATTERN, text, re.I)
    if m:
        return f"needs Claude: matched {m.group(0)!r}"
    return None


# ------------------------------------------------- history -> Anthropic
def history_for_claude(history: list[dict]) -> list[dict]:
    """The history with any `LLMBlock`s turned into plain dicts the SDK can send. Returns `history` itself when none are present."""
    if not any(isinstance(b, LLMBlock) for m in history if isinstance(m["content"], list) for b in m["content"]):
        return history
    out = []
    for m in history:
        if isinstance(m["content"], list):
            m = {**m, "content": [b.to_dict() if isinstance(b, LLMBlock) else b for b in m["content"]]}
        out.append(m)
    return out


# ----------------------------------------------- history -> OpenAI style
def _get(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function",
             "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}}
            for t in tools]


def to_openai_messages(system: str, history: list[dict]) -> list[dict]:
    """Anthropic-shaped history -> chat-completions messages. A tool result whose call isn't in the window is dropped."""
    out: list[dict] = [{"role": "system", "content": system}]
    live_calls: set[str] = set()
    for m in history:
        content = m["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if m["role"] == "assistant":
            texts = [_get(b, "text", "") for b in content if _get(b, "type") == "text"]
            calls = []
            for b in content:
                if _get(b, "type") == "tool_use":
                    live_calls.add(_get(b, "id"))
                    calls.append({"id": _get(b, "id"), "type": "function",
                                  "function": {"name": _get(b, "name"), "arguments": json.dumps(_get(b, "input") or {})}})
            msg: dict = {"role": "assistant", "content": " ".join(t for t in texts if t) or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            texts = []
            for b in content:
                kind = _get(b, "type")
                if kind == "tool_result":
                    if _get(b, "tool_use_id") in live_calls:
                        out.append({"role": "tool", "tool_call_id": _get(b, "tool_use_id"),
                                    "content": str(_get(b, "content", ""))})
                elif kind == "text":
                    texts.append(_get(b, "text", ""))
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
    return out


def parse_openai_response(data: dict) -> LLMResponse:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    blocks: list[LLMBlock] = []
    if msg.get("content"):
        blocks.append(LLMBlock("text", text=str(msg["content"])))
    for call in msg.get("tool_calls") or []:
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        blocks.append(LLMBlock("tool_use", id=call.get("id", ""), name=fn.get("name", ""),
                               input=args if isinstance(args, dict) else {}))
    return LLMResponse(content=blocks, stop_reason=choice.get("finish_reason") or "")


# --------------------------------------------------------------- backend
def _http_post(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, Any]:
    import httpx
    try:
        r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise LLMError("transient", type(e).__name__) from e
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"error": r.text[:200]}


class OpenAICompatLLM:
    """Any server speaking `POST {base_url}/chat/completions` with tool calls (hosted free tiers, OpenRouter, Groq, Ollama, ...).
    `post` is injectable so tests never touch the network."""

    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int, timeout_s: float,
                 post: Callable[[str, dict, dict, float], tuple[int, Any]] = _http_post):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self._post = post

    def create(self, system: str, tools: list[dict], messages: list[dict]) -> LLMResponse:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "max_tokens": self.max_tokens,
                   "messages": to_openai_messages(system, messages), "tools": to_openai_tools(tools)}
        status, data = self._post(f"{self.base_url}/chat/completions", headers, payload, self.timeout_s)
        if status in (401, 403):
            raise LLMError("auth", f"HTTP {status}")
        if status == 402:
            raise LLMError("billing", f"HTTP {status}")
        if status == 429:
            raise LLMError("rate", f"HTTP {status}")
        if status >= 400:
            raise LLMError("transient", f"HTTP {status}: {data}")
        return parse_openai_response(data)
