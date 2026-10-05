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
import re
import threading
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


def _http_client_kwargs(keepalive_s: float) -> dict:
    """`http_client=` for anthropic.Anthropic with a longer keep-alive; {} (SDK default) if anything is off."""
    try:
        try:
            import httpx2 as httpx
        except ImportError:
            import httpx
        return {"http_client": anthropic.DefaultHttpxClient(
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=2, keepalive_expiry=keepalive_s))}
    except Exception:  # noqa: BLE001
        log.debug("custom keep-alive unavailable; using the SDK default connection pool", exc_info=True)
        return {}

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
            },
            "seconds": {
                "type": "number",
                "description": (
                    "Only for looping gaits (walk, trot, crawl): how many seconds to keep "
                    f"going before stopping, at most {int(skills.MAX_GAIT_SECONDS)}. Use it "
                    "when the person says how long or how far (\"walk for ten seconds\"; "
                    "estimate seconds for a distance). Omit for one-shot skills and for "
                    "open-ended requests."
                ),
            },
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
        "Also use it for lasting facts about YOU, G2 -- for example what you look like once you have seen yourself in a mirror "
        "(\"I look like ...\"). "
        "NEVER record dates, clock times, schedules, routines, or anyone's "
        "comings and goings / whereabouts over time -- keep stable facts about "
        "people and preferences, not a timeline of their lives. "
        "You may reply and call this in the same turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "The fact to remember."},
            "importance": {"type": "integer", "minimum": 1, "maximum": 5,
                           "description": "How much this will matter later: 5 = identity-level (names, who lives here, pets, allergies, "
                                          "how you look), 3 = ordinary preference or situation, 1 = barely worth keeping."},
            "core": {"type": "boolean",
                     "description": "true only for identity-level facts that should ALWAYS be in mind and never rotate out: who lives here, "
                                    "the pets' names, what you look like. Most facts are not core."},
        },
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

_AWAIT_REPLY_TOOL = {
    "name": "await_reply",
    "description": (
        "Call this when you have just asked the person a question (or are otherwise waiting for their answer), so G2 keeps "
        "listening for a few seconds without needing the wake word. Do not call it for statements or rhetorical questions. "
        "You can reply in the same turn."
    ),
    "input_schema": {"type": "object", "properties": {}},
}

def _describe_block(b) -> str:
    """One short token per reply block for the log. A thinking block shows the start of its text: this model writes its short
    between-tool updates there, and a reply that is only a thinking block plus a tool call is a silent reply."""
    if b.type == "text":
        return f"text({len(b.text)})"
    if b.type == "thinking":
        t = (getattr(b, "thinking", "") or "").strip().replace("\n", " ")
        return f"thinking({len(t)}){': ' + repr(t[:100]) if t else ''}"
    return f"{b.type}:{getattr(b, 'name', '')}"


def _is_thinking_binding_error(e: Exception) -> bool:
    """The API's 400 for a thinking block whose signature no longer matches the conversation before it."""
    text = str(e).lower()
    return type(e).__name__ == "BadRequestError" and "thinking" in text and ("signature" in text or "bound to a different conversation" in text)


_SPEAK_NOW = ("[You said nothing out loud. Answer the person now, out loud, in words only (no tools). If there was a picture, "
              "describe what you see in it.]")

_TOOLS = [_PERFORM_SKILL_TOOL, _REMEMBER_TOOL, _DIAGNOSTICS_TOOL, _AWAIT_REPLY_TOOL]

# When the user asks what G2 sees, the voice loop attaches a picture from G2's own camera to that message.
_PICTURE_NOTE = (
    "Sometimes the user's message comes with a small picture from your own camera (low resolution, often dim). When it does, describe "
    "what you actually see in one or two short spoken sentences, from your own point of view. Always speak the description first: the "
    "camera has already taken the picture, so do not use the check_around skill or any other move to \"look\" -- just say what you see. "
    "A note next to the picture says what "
    "the small on-device detector thought it saw; treat that as a hint only. If a note says the camera could not take a picture, "
    "say so plainly. If someone asks what you look like and there is no picture, answer from the \"I look like ...\" note you remember; if "
    "you do not remember, say so and suggest showing you a mirror -- do not invent. If the picture shows a small robot (for example in a mirror), that is you, G2: say so and describe how you look. "
    "Never invent things you cannot see.")

_ENDS_WITH_QUESTION = re.compile(r"\?[\"')\]\s]*$")


class ConversationError(RuntimeError):
    """A Claude call failed for a *known, non-transient* reason. `spoken` is the
    in-character line for G2 to say; `kind` is one of 'auth' / 'rate' / 'billing'.
    `voice/loop.py` catches this before its generic handler."""

    def __init__(self, kind: str, spoken: str):
        super().__init__(f"{kind}: {spoken}")
        self.kind = kind
        self.spoken = spoken


class SentenceSplitter:
    """Turns streamed text deltas into whole sentences, so speech can start before the reply is finished."""

    _END = re.compile(r"(?<=[.!?])\s+")

    def __init__(self):
        self._buf = ""

    def feed(self, text: str) -> list[str]:
        self._buf += text
        parts = self._END.split(self._buf)
        self._buf = parts.pop()          # the unfinished tail (or "" right after a sentence end + space)
        return [p.strip() for p in parts if p.strip()]

    def flush(self) -> str:
        rest, self._buf = self._buf.strip(), ""
        return rest


@dataclass
class AssistantTurn:
    speech: str
    actions: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    action_seconds: list[float | None] = field(default_factory=list)   # parallel to `actions`
    fact_details: list = field(default_factory=list)   # (fact, importance 1-5, core) for each `remember` call, parallel to `facts`
    expects_reply: bool = False   # G2 asked a question: listen briefly for the answer without the wake word
    streamed: bool = False   # True when `on_action`/`on_speech` already delivered the speech and actions as they arrived


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
            api_key=cfg.require_api_key(), timeout=cfg.request_timeout_s,
            **_http_client_kwargs(cfg.api_keepalive_s),
        )
        self._streamed = False
        self._first_event_t = None
        self.last_call: dict = {}          # {"start", "end", "backend"} of the most recent turn (monotonic seconds)
        self.warm_info: dict = {}          # result of the last background connection warm-up
        self._base_system = cfg.system_prompt.rstrip() + "\n\n" + _PICTURE_NOTE
        p = personality or Personality.from_settings(cfg)
        self._personality = p
        self._mood_hint = ""
        self._narration_hint = ""
        self._rebuild_system()
        if p.traits:
            log.info("personality: %s", p.describe())
        self._history: list[dict] = []
        self._pending_tool_results: list[dict] = []
        self._fact_details: list = []
        from .usage import UsageTracker
        self._usage = UsageTracker(cfg.usage_path) if getattr(cfg, "usage_path", "") else None

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

    def _strip_thinking(self) -> None:
        """Remove thinking / redacted_thinking blocks from every stored assistant message."""
        for m in self._history:
            if m["role"] == "assistant" and isinstance(m["content"], list):
                m["content"] = [b for b in m["content"]
                                if (b.get("type") if isinstance(b, dict) else getattr(b, "type", None)) not in ("thinking", "redacted_thinking")]

    def _trim(self) -> None:
        max_msgs = max(2, self._cfg.history_turns * 2)
        if len(self._history) > max_msgs:
            # drop whole turns from the front; never start on an assistant msg
            self._history = self._history[-max_msgs:]
            while self._history and self._history[0]["role"] != "user":
                self._history.pop(0)

    def _call_with_retries(self, call, delivered=lambda: False):
        """Run `call()` with the retry / spoken-error policy. Once `delivered()` is true the caller has already
        acted on part of a streamed reply, so a failure is raised instead of retried (no repeated moves or speech)."""
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                return call()
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
                log.error("Claude auth failed (%s) -- key invalid/expired/blocked", type(e).__name__)
                raise ConversationError("auth", self._cfg.speech_api_auth) from e
            except anthropic.BadRequestError as e:
                if any(w in str(e).lower() for w in ("credit", "billing", "balance", "quota")):
                    log.error("Claude billing/quota block: %s", e)
                    raise ConversationError("billing", self._cfg.speech_api_billing) from e
                raise
            except anthropic.RateLimitError as e:
                if delivered():
                    raise
                last_err = e
                log.warning("Claude rate-limited; attempt %d/3", attempt + 1)
                time.sleep(2.0 * (attempt + 1))
            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
                if delivered():
                    raise
                last_err = e
                log.warning("Claude call failed (%s); attempt %d/3", type(e).__name__, attempt + 1)
                time.sleep(1.0 + attempt)
        if isinstance(last_err, anthropic.RateLimitError):
            raise ConversationError("rate", self._cfg.speech_api_rate) from last_err
        raise last_err  # type: ignore[misc]

    def _create(self, **kw):
        return self._call_with_retries(lambda: self._client.messages.create(**kw))

    def _create_stream(self, kw, on_action, on_speech):
        """Stream one Claude reply. Each completed sentence goes to `on_speech` and each `perform_skill` call to
        `on_action` the moment it is complete; the finished message is returned for history and bookkeeping."""
        state = {"delivered": False}

        def _once():
            splitter = SentenceSplitter()
            self._first_event_t = None
            with self._client.messages.stream(**kw) as stream:
                for ev in stream:
                    if self._first_event_t is None:
                        self._first_event_t = time.monotonic()
                    if ev.type == "text":
                        for sentence in splitter.feed(ev.text):
                            state["delivered"] = True
                            on_speech(sentence)
                    elif ev.type == "content_block_stop":
                        blk = getattr(ev, "content_block", None)
                        if getattr(blk, "type", None) == "text":      # the text block is done: speak its last sentence now
                            rest = splitter.flush()
                            if rest:
                                state["delivered"] = True
                                on_speech(rest)
                        elif getattr(blk, "type", None) == "tool_use" and getattr(blk, "name", "") == "perform_skill":
                            inp = blk.input or {}
                            name = inp.get("skill", "")
                            if skills.is_valid(name):
                                state["delivered"] = True
                                on_action(name, skills.clamp_seconds(inp.get("seconds")))
                rest = splitter.flush()
                if rest:
                    state["delivered"] = True
                    on_speech(rest)
                return stream.get_final_message()

        return self._call_with_retries(_once, delivered=lambda: state["delivered"])

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

    def _complete(self, user_text: str, memory_context: str | None, on_action=None, on_speech=None, force_claude: bool = False,
                  tool_choice: dict | None = None):
        """Pick a backend for this turn and get its reply. Returns (response, backend name). With both callbacks
        given, a Claude reply is streamed through them (`self._streamed` says whether that happened)."""
        self._streamed = False
        if self._fast is not None and not force_claude:      # a picture can only go to Claude
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
        kw = dict(
            model=self._cfg.claude_model,
            max_tokens=self._cfg.claude_max_tokens,
            system=self._system_prompt,
            tools=_TOOLS,
            messages=history_for_claude(self._history),
            **({"output_config": {"effort": self._cfg.claude_effort}} if self._cfg.claude_effort else {}),
            **({"tool_choice": tool_choice} if tool_choice else {}),
        )
        if on_action is not None and on_speech is not None and hasattr(self._client.messages, "stream"):
            self._streamed = True
            return self._create_stream(kw, on_action, on_speech), "claude"
        return self._create(**kw), "claude"

    def _digest(self, resp, picture) -> tuple[list[str], list[str], list, list[str], bool]:
        """Store an assistant reply in the history and sort it into (speech parts, skills to perform, their seconds, facts to remember,
        whether a reply is expected). Tool calls are acknowledged for the next user message."""
        stored = resp.content
        if picture is not None:
            # a thinking block is bound to everything before it, and the picture in this turn's user message is about to be
            # replaced by a placeholder: keep no thinking blocks from a picture turn
            stored = [b for b in resp.content if getattr(b, "type", None) not in ("thinking", "redacted_thinking")]
        self._history.append({"role": "assistant", "content": stored})

        speech_parts: list[str] = []
        actions: list[str] = []
        action_seconds: list[float | None] = []
        facts: list[str] = []
        expects_reply = False
        for block in resp.content:
            if block.type == "text":
                speech_parts.append(block.text.strip())
            elif block.type == "tool_use" and block.name == "perform_skill":
                name = (block.input or {}).get("skill", "")
                ok = skills.is_valid(name)
                if ok:
                    actions.append(name)
                    action_seconds.append(skills.clamp_seconds((block.input or {}).get("seconds")))
                else:
                    log.warning("Claude asked for unknown skill %r", name)
                self._ack(block.id, "done" if ok else f"unknown skill {name!r}")
            elif block.type == "tool_use" and block.name == "await_reply":
                expects_reply = True
                self._ack(block.id, "listening for the answer")
            elif block.type == "tool_use" and block.name == "remember":
                fact = (block.input or {}).get("fact", "").strip()
                if fact:
                    facts.append(fact)
                    inp = block.input or {}
                    try:
                        importance = max(1, min(5, int(inp.get("importance", 3))))
                    except (TypeError, ValueError):
                        importance = 3
                    self._fact_details.append((fact, importance, bool(inp.get("core", False))))
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

        return speech_parts, actions, action_seconds, facts, expects_reply

    def send(self, user_text: str, memory_context: str | None = None, *, on_action=None, on_speech=None,
             image: bytes | None = None, image_note: str | None = None) -> AssistantTurn:
        # one turn: sends the user text (+ any pending tool acks), then sorts
        # the reply into speech + skills to perform + facts to remember
        self._fact_details = []
        acks = list(self._pending_tool_results)
        blocks: list[dict] = list(acks)
        self._pending_tool_results = []
        if memory_context:
            blocks.append({
                "type": "text",
                "text": f"[Memory of past conversations]\n{memory_context}",
            })
        picture = None
        if image is not None:                       # a snapshot from G2's camera, sent with this one message only
            import base64
            picture = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": base64.b64encode(image).decode("ascii")}}
            blocks.append(picture)
        if image_note:
            blocks.append({"type": "text", "text": image_note})
        blocks.append({"type": "text", "text": user_text})
        self._history.append({"role": "user", "content": blocks})

        t0 = time.monotonic()
        try:
            try:
                resp, backend = self._complete(user_text, memory_context, on_action, on_speech,
                                               force_claude=image is not None or bool(image_note))
            except Exception as e:  # noqa: BLE001
                if not _is_thinking_binding_error(e):
                    raise
                # a thinking block no longer matches the history before it: drop them all and try once more
                log.warning("API rejected a thinking block (%s); dropping thinking blocks from the history and retrying", e)
                self._strip_thinking()
                resp, backend = self._complete(user_text, memory_context, on_action, on_speech,
                                               force_claude=image is not None or bool(image_note))
        except Exception:
            # a failed turn must not poison the history: take this user message back out and keep its tool acks for next time
            if self._history and self._history[-1] is not None and self._history[-1].get("content") is blocks:
                self._history.pop()
            self._pending_tool_results = acks + self._pending_tool_results
            raise
        self.last_call = {"start": t0, "end": time.monotonic(), "backend": backend,
                          "first": getattr(self, "_first_event_t", None) if self._streamed else None}
        log.info("%s replied in %.1fs (stop=%s)", backend, time.monotonic() - t0, resp.stop_reason)
        log.info("reply blocks: %s", ", ".join(_describe_block(b) for b in resp.content) or "none")
        if self._usage is not None and backend == "claude":
            self._usage.record("turn", getattr(resp, "usage", None))

        speech_parts, actions, action_seconds, facts, expects_reply = self._digest(resp, picture)
        if not any(speech_parts) and (picture is not None or not actions):
            # nothing was said and no move answered the request: ask once more for words only, so a question is never left unanswered
            log.warning("reply had no speech (%s); asking once more for words only",
                        ", ".join(_describe_block(b) for b in resp.content) or "empty")
            retry_blocks = list(self._pending_tool_results) + [{"type": "text", "text": _SPEAK_NOW}]
            self._pending_tool_results = []
            self._history.append({"role": "user", "content": retry_blocks})
            try:
                resp2, _ = self._complete(user_text, memory_context, on_action, on_speech, force_claude=True,
                                          tool_choice={"type": "none"})
                log.info("retry reply blocks: %s", ", ".join(_describe_block(b) for b in resp2.content) or "none")
                if self._usage is not None:
                    self._usage.record("retry", getattr(resp2, "usage", None))
                s2, a2, sec2, f2, e2 = self._digest(resp2, picture)
                speech_parts += s2; actions += a2; action_seconds += sec2; facts += f2; expects_reply = expects_reply or e2
            except Exception:  # noqa: BLE001 -- the first reply stands; take the retry message back out and keep its acks
                log.warning("the words-only retry failed", exc_info=True)
                if self._history and self._history[-1].get("content") is retry_blocks:
                    self._history.pop()
                self._pending_tool_results = [b for b in retry_blocks if b.get("type") == "tool_result"] + self._pending_tool_results
        if picture is not None and picture in blocks:         # never keep (or resend) the picture in the history
            blocks[blocks.index(picture)] = {"type": "text", "text": "[a picture from G2's camera was shown here]"}
        self._trim()
        speech = " ".join(p for p in speech_parts if p)
        if speech and _ENDS_WITH_QUESTION.search(speech):
            expects_reply = True                 # the reply ends in a question
        return AssistantTurn(
            speech=speech, actions=actions, facts=facts, fact_details=list(self._fact_details),
            action_seconds=action_seconds, streamed=self._streamed, expects_reply=expects_reply,
        )

    @property
    def supports_streaming(self) -> bool:
        """True when replies can be streamed (the Claude client is in use)."""
        return bool(self._cfg.stream_replies) and self._client is not None and hasattr(self._client.messages, "stream")

    def warm_up(self) -> None:
        """Open the API connection in the background (a free model-list lookup, no tokens), so the
        TCP+TLS handshake happens while the person is still speaking. Safe to call every wake word."""
        if self._client is None or not self._cfg.api_warmup:
            return
        if self.warm_info.get("running"):
            return
        self.warm_info = {"running": True, "t_start": time.monotonic()}

        def _go() -> None:
            info = self.warm_info
            try:
                self._client.models.list(limit=1)
                info["ok"] = True
            except Exception as e:  # noqa: BLE001 -- warming is best-effort
                info["ok"] = False
                log.debug("api warm-up failed: %s", e)
            info["t_end"] = time.monotonic()
            info["running"] = False
            log.debug("api warm-up %.2fs ok=%s", info["t_end"] - info["t_start"], info["ok"])

        threading.Thread(target=_go, name="api-warmup", daemon=True).start()

    def _ack(self, tool_use_id: str, content: str) -> None:
        self._pending_tool_results.append({
            "type": "tool_result", "tool_use_id": tool_use_id, "content": content,
        })
