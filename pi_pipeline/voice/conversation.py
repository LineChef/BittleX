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
from ..personality import Personality
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

_REMEMBER_TOOL = {
    "name": "remember",
    "description": (
        "Save one short, durable fact worth keeping across future "
        "conversations -- the person's name, things they like or own, ongoing "
        "situations, stable preferences. Not small talk or one-off details. "
        "Write it as a standalone sentence (\"Their name is Sam.\", \"They have "
        "a cat named Biscuit.\"). "
        "NEVER record dates, clock times, schedules, routines, or anyone's "
        "comings and goings / whereabouts over time -- keep stable facts about "
        "people and preferences, not a timeline of their lives. "
        "You may reply and call this in the same turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"fact": {"type": "string", "description": "The fact to remember."}},
        "required": ["fact"],
    },
}

_TOOLS = [_PERFORM_SKILL_TOOL, _REMEMBER_TOOL]


class ConversationError(RuntimeError):
    """A Claude call failed for a *known, non-transient* reason. `spoken` is the
    in-character line for G2 to say; `kind` is one of 'auth' / 'rate' / 'billing'.
    `voice/loop.py` catches this before its generic handler."""

    def __init__(self, kind: str, spoken: str):
        super().__init__(f"{kind}: {spoken}")
        self.kind = kind
        self.spoken = spoken


@dataclass
class AssistantTurn:
    speech: str
    actions: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)


class Conversation:
    def __init__(self, cfg: Settings, personality: Personality | None = None):
        self._cfg = cfg
        self._client = anthropic.Anthropic(
            api_key=cfg.require_api_key(), timeout=cfg.request_timeout_s
        )
        self._base_system = cfg.system_prompt
        p = personality or Personality.from_settings(cfg)
        self._personality = p
        self._mood_hint = ""
        self._rebuild_system()
        if p.traits:
            log.info("personality: %s", p.describe())
        self._history: list[dict] = []
        self._pending_tool_results: list[dict] = []

    @property
    def personality(self) -> Personality:
        return self._personality

    def _rebuild_system(self) -> None:
        """Compose the live system prompt: base + personality fragments + an
        optional slow-mood line. Called on any personality / mood change."""
        s = self._personality.system_prompt(self._base_system)
        if self._mood_hint:
            s = s.rstrip() + "\n\n" + self._mood_hint
        self._system_prompt = s

    def set_personality(self, p: Personality) -> None:
        """Swap the personality mid-session (e.g. the user asks to enable a
        character mode). Rebuilds the system prompt; history is kept."""
        self._personality = p
        self._rebuild_system()
        log.info("personality now: %s", p.describe())

    def set_mood_hint(self, hint: str) -> None:
        """Set (or clear, with "") the one-line mood note the mood model
        produces. Cheap -- call it every turn; only rebuilds on a change."""
        hint = (hint or "").strip()
        if hint != self._mood_hint:
            self._mood_hint = hint
            self._rebuild_system()

    def _trim(self) -> None:
        max_msgs = max(2, self._cfg.history_turns * 2)
        if len(self._history) > max_msgs:
            # drop whole turns from the front; never start on an assistant msg
            self._history = self._history[-max_msgs:]
            while self._history and self._history[0]["role"] != "user":
                self._history.pop(0)

    def _create(self, **kw):
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                return self._client.messages.create(**kw)
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
                log.error("Claude auth failed (%s) -- key invalid/expired/blocked", type(e).__name__)
                raise ConversationError("auth", self._cfg.speech_api_auth) from e
            except anthropic.BadRequestError as e:
                if any(w in str(e).lower() for w in ("credit", "billing", "balance", "quota")):
                    log.error("Claude billing/quota block: %s", e)
                    raise ConversationError("billing", self._cfg.speech_api_billing) from e
                raise
            except anthropic.RateLimitError as e:
                last_err = e
                log.warning("Claude rate-limited; attempt %d/3", attempt + 1)
                time.sleep(2.0 * (attempt + 1))
            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
                last_err = e
                log.warning("Claude call failed (%s); attempt %d/3", type(e).__name__, attempt + 1)
                time.sleep(1.0 + attempt)
        if isinstance(last_err, anthropic.RateLimitError):
            raise ConversationError("rate", self._cfg.speech_api_rate) from last_err
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
            system=self._system_prompt,
            tools=_TOOLS,
            messages=self._history,
        )
        log.info("Claude replied in %.1fs (stop=%s)", time.monotonic() - t0, resp.stop_reason)

        self._history.append({"role": "assistant", "content": resp.content})

        speech_parts: list[str] = []
        actions: list[str] = []
        facts: list[str] = []
        for block in resp.content:
            if block.type == "text":
                speech_parts.append(block.text.strip())
            elif block.type == "tool_use" and block.name == "perform_skill":
                name = (block.input or {}).get("skill", "")
                ok = skills.is_valid(name)
                if ok:
                    actions.append(name)
                else:
                    log.warning("Claude asked for unknown skill %r", name)
                self._ack(block.id, "done" if ok else f"unknown skill {name!r}")
            elif block.type == "tool_use" and block.name == "remember":
                fact = (block.input or {}).get("fact", "").strip()
                if fact:
                    facts.append(fact)
                self._ack(block.id, "saved" if fact else "empty fact, not saved")

        self._trim()
        return AssistantTurn(
            speech=" ".join(p for p in speech_parts if p), actions=actions, facts=facts
        )

    def _ack(self, tool_use_id: str, content: str) -> None:
        self._pending_tool_results.append({
            "type": "tool_result", "tool_use_id": tool_use_id, "content": content,
        })
