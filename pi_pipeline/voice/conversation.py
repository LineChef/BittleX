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
from ..diag.core import last_failure, summarize_session
from ..features import features
from ..personality import Personality
from . import skills
from .llm import (LLMError, OpenAICompatLLM, history_for_claude, needs_claude)

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

_DIAGNOSTICS_TOOL = {
    "name": "diagnostics_query",
    "description": (
        "Look up G2's own diagnostic data to answer questions about what "
        "happened, why something failed, or what mode G2 is running in. Use "
        "this for things like 'why did you fall', 'what happened just now', "
        "'are you okay', or 'what features are you running with'. The result "
        "comes back as plain text on your *next* reply, not this one -- so "
        "acknowledge the question now (e.g. \"let me check\") and give the "
        "real answer, in your own words, once you have it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "enum": ["summary", "last_failure", "status"],
                "description": (
                    "'summary' = overview of the current/most recent session "
                    "(events, thermal state, warnings). 'last_failure' = the "
                    "most recent fall/stall/error, what and when. 'status' = "
                    "which features/modes are currently enabled."
                ),
            }
        },
        "required": ["topic"],
    },
}

_TOOLS = [_PERFORM_SKILL_TOOL, _REMEMBER_TOOL, _DIAGNOSTICS_TOOL]


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
        if cfg.llm_mode not in ("claude", "fast", "routed"):
            raise RuntimeError(f"G2_LLM_MODE must be claude, fast or routed (got {cfg.llm_mode!r})")
        self._fast: OpenAICompatLLM | None = None
        if cfg.llm_mode in ("fast", "routed"):
            if not (cfg.fast_llm_base_url and cfg.fast_llm_model):
                raise RuntimeError("G2_LLM_MODE=%s needs G2_FAST_LLM_BASE_URL and G2_FAST_LLM_MODEL (see .env.example)"
                                   % cfg.llm_mode)
            self._fast = OpenAICompatLLM(cfg.fast_llm_base_url, cfg.fast_llm_api_key, cfg.fast_llm_model,
                                         cfg.claude_max_tokens, cfg.request_timeout_s)
        self._client = None if cfg.llm_mode == "fast" else anthropic.Anthropic(
            api_key=cfg.require_api_key(), timeout=cfg.request_timeout_s
        )
        self._base_system = cfg.system_prompt
        p = personality or Personality.from_settings(cfg)
        self._personality = p
        self._mood_hint = ""
        self._narration_hint = ""
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
        optional slow-mood line + an optional narration-verbosity line. Called
        on any personality / mood / verbosity change."""
        s = self._personality.system_prompt(self._base_system)
        if self._mood_hint:
            s = s.rstrip() + "\n\n" + self._mood_hint
        if self._narration_hint:
            s = s.rstrip() + "\n\n" + self._narration_hint
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

    def set_narration_hint(self, hint: str) -> None:
        """Set (or clear, with "") how much G2 narrates its own actions/
        reasoning -- voice: 'explain more' / 'keep it brief'. Session-only,
        like the mood hint; doesn't persist across restarts."""
        hint = (hint or "").strip()
        if hint != self._narration_hint:
            self._narration_hint = hint
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

    def _fast_create(self):
        """One call to the fast backend. Auth/billing/rate failures raise a spoken ConversationError in fast-only mode;
        in routed mode every failure raises LLMError so the caller can fall back to Claude."""
        try:
            return self._fast.create(self._system_prompt, _TOOLS, self._history)
        except LLMError as e:
            if self._cfg.llm_mode == "fast" and e.kind in ("auth", "billing", "rate"):
                log.error("fast LLM %s failure: %s", e.kind, e)
                spoken = {"auth": self._cfg.speech_api_auth, "billing": self._cfg.speech_api_billing,
                          "rate": self._cfg.speech_api_rate}[e.kind]
                raise ConversationError(e.kind, spoken) from e
            raise

    def _complete(self, user_text: str, memory_context: str | None):
        """Pick a backend for this turn and get its reply. Returns (response, backend name)."""
        if self._fast is not None:
            why = None
            if self._cfg.llm_mode == "routed":
                why = needs_claude(user_text, memory_context, sees_memory=self._cfg.fast_llm_sees_memory,
                                   max_words=self._cfg.route_max_words, pattern=self._cfg.route_escalate_pattern)
            if why is None:
                try:
                    resp = self._fast_create()
                    if self._cfg.llm_mode == "fast" or any(
                            b.type == "tool_use" or (b.type == "text" and b.text.strip()) for b in resp.content):
                        return resp, "fast"
                    log.warning("fast LLM returned an empty reply; falling back to Claude")
                except LLMError as e:
                    if self._cfg.llm_mode == "fast":
                        raise
                    log.warning("fast LLM failed (%s); falling back to Claude", e)
            else:
                log.info("routing to Claude: %s", why)
        resp = self._create(
            model=self._cfg.claude_model,
            max_tokens=self._cfg.claude_max_tokens,
            system=self._system_prompt,
            tools=_TOOLS,
            messages=history_for_claude(self._history),
        )
        return resp, "claude"

    def send(self, user_text: str, memory_context: str | None = None) -> AssistantTurn:
        # one turn: sends the user text (+ any pending tool acks), then sorts
        # the reply into speech + skills to perform + facts to remember
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
        resp, backend = self._complete(user_text, memory_context)
        log.info("%s replied in %.1fs (stop=%s)", backend, time.monotonic() - t0, resp.stop_reason)

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
            elif block.type == "tool_use" and block.name == "diagnostics_query":
                topic = (block.input or {}).get("topic", "summary")
                try:
                    if topic == "last_failure":
                        result = last_failure()
                    elif topic == "status":
                        result = features.describe()
                    else:
                        result = summarize_session()
                except Exception:  # noqa: BLE001 -- a lookup failure must not kill the turn
                    log.exception("diagnostics_query(%r) failed", topic)
                    result = "diagnostics lookup failed -- nothing usable to report."
                self._ack(block.id, result)

        self._trim()
        return AssistantTurn(
            speech=" ".join(p for p in speech_parts if p), actions=actions, facts=facts
        )

    def _ack(self, tool_use_id: str, content: str) -> None:
        self._pending_tool_results.append({
            "type": "tool_result", "tool_use_id": tool_use_id, "content": content,
        })
