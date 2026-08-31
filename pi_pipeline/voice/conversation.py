"""The conversation layer: wraps the Anthropic client, keeps rolling history,
and turns each Claude reply into something the loop can act on -- text to speak
plus a list of physical skills to perform.

Design notes:
- One API call per turn. Claude may return spoken text *and* `perform_skill`
  tool calls in the same response; we speak the text and run the skills, then
  acknowledge the tool calls (a trivial tool_result) on the *next* user turn, so
  there's no second round-trip just to close the loop.
- `send()` accepts an optional `memory_context` string. Phase 9's memory module
  will supply retrieved past context there; until then it's None. This is the
  only seam memory needs.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import anthropic

from ..config import Settings
from . import skills

log = logging.getLogger("g2.conversation")

_PERFORM_SKILL_TOOL = {
    "name": "perform_skill",
    "description": (
        "Make the G2 robot perform one physical skill (a gait, posture, or "
        "gesture). Call this when moving fits the conversation. You may also "
        "reply with spoken text in the same response. Available skills:\n"
        + skills.catalogue_for_prompt()
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "enum": list(skills.SKILLS.keys()),
                "description": "The skill to perform.",
            }
        },
        "required": ["skill"],
    },
}


@dataclass
class AssistantTurn:
    speech: str
    actions: list[str] = field(default_factory=list)


class Conversation:
    def __init__(self, cfg: Settings):
        self._cfg = cfg
        self._client = anthropic.Anthropic(
            api_key=cfg.require_api_key(), timeout=cfg.request_timeout_s
        )
        self._history: list[dict] = []
        self._pending_tool_results: list[dict] = []

    def _trim(self) -> None:
        max_msgs = max(2, self._cfg.history_turns * 2)
        if len(self._history) > max_msgs:
            # drop whole turns from the front; never start on an assistant msg
            self._history = self._history[-max_msgs:]
            while self._history and self._history[0]["role"] != "user":
                self._history.pop(0)

    def _create(self, **kw):
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                return self._client.messages.create(**kw)
            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
                last_err = e
                log.warning("Claude call failed (%s); attempt %d", type(e).__name__, attempt + 1)
                time.sleep(1.0 + attempt)
        raise last_err  # type: ignore[misc]

    def send(self, user_text: str, memory_context: str | None = None) -> AssistantTurn:
        blocks: list[dict] = list(self._pending_tool_results)
        self._pending_tool_results = []
        if memory_context:
            blocks.append({
                "type": "text",
                "text": f"[Memory of past conversations]\n{memory_context}",
            })
        blocks.append({"type": "text", "text": user_text})
        self._history.append({"role": "user", "content": blocks})

        t0 = time.monotonic()
        resp = self._create(
            model=self._cfg.claude_model,
            max_tokens=self._cfg.claude_max_tokens,
            system=self._cfg.system_prompt,
            tools=[_PERFORM_SKILL_TOOL],
            messages=self._history,
        )
        log.info("Claude replied in %.1fs (stop=%s)", time.monotonic() - t0, resp.stop_reason)

        self._history.append({"role": "assistant", "content": resp.content})

        speech_parts: list[str] = []
        actions: list[str] = []
        for block in resp.content:
            if block.type == "text":
                speech_parts.append(block.text.strip())
            elif block.type == "tool_use" and block.name == "perform_skill":
                name = (block.input or {}).get("skill", "")
                if skills.is_valid(name):
                    actions.append(name)
                else:
                    log.warning("Claude asked for unknown skill %r", name)
                self._pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "done" if skills.is_valid(name) else f"unknown skill {name!r}",
                })

        self._trim()
        return AssistantTurn(speech=" ".join(p for p in speech_parts if p), actions=actions)
