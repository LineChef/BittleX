# Swappable LLM — Claude, a cheaper model, or both

G2's conversation layer (`pi_pipeline/voice/conversation.py`) can answer with Claude, with any OpenAI-style chat model, or with both: a fast
backend for casual turns and Claude for the rest. The goal is to run G2 without paying for every sentence. Code: `pi_pipeline/voice/llm.py`.

## Change the Claude model

Set `CLAUDE_MODEL` in `.env` (default in `pi_pipeline/config.py`), e.g. `CLAUDE_MODEL=<model id>`. No code change. `CLAUDE_MAX_TOKENS` and
`CLAUDE_TIMEOUT_S` sit beside it. `G2_CLAUDE_EFFORT` (default `low`) sets how long Claude thinks before answering; thinking tokens count toward
`CLAUDE_MAX_TOKENS`, so a low effort keeps replies quick and un-truncated. Empty means the model's own default.

## Modes (`G2_LLM_MODE` in `.env`)

| Mode | What answers | Needs |
|---|---|---|
| `claude` (default) | Claude for every turn | `ANTHROPIC_API_KEY` |
| `fast` | the fast backend only; nothing is sent to Anthropic | the three `G2_FAST_LLM_*` values below; no Anthropic key |
| `routed` | the fast backend for casual turns; Claude when the router says so, or when the fast backend fails | both |

The fast backend is any server that speaks `POST {base}/chat/completions` with tool calls: hosted free or cheap tiers, aggregators, or a local
server. Set `G2_FAST_LLM_BASE_URL` (up to and including `/v1`), `G2_FAST_LLM_API_KEY` and `G2_FAST_LLM_MODEL`. The model should support tool
calling, since G2 uses tools for skills, memory and diagnostics. See `.env.example` for all the knobs.

## How `routed` decides

`needs_claude()` in `llm.py` sends a turn to Claude when any of these hold:

- there is recalled memory for the turn (personal; kept off the fast backend unless `G2_FAST_LLM_SEES_MEMORY=1`);
- the request is longer than `G2_ROUTE_MAX_WORDS` (default 25);
- it matches the escalation pattern: personal statements ("my", "I'm", "remember"), vision and diagnostics questions, and reasoning requests
  ("explain", "how do", "plan", "compare", "write", ...). Override with `G2_ROUTE_ESCALATE_PATTERN`.

Everything else goes to the fast backend. If the fast backend errors or returns an empty reply, the turn is retried on Claude. The log says
which backend answered each turn, and why a turn was routed to Claude.

The rules are deliberately conservative (more turns to Claude, fewer to the fast model). Loosen them once the fast model's quality on G2's
tools and personality is known.

## What leaves the device

The user's words for each turn go to whichever backend answers it. In `routed` mode the fast backend receives the system prompt, the rolling
conversation history, and the tool definitions; recalled memory is withheld by default. A hosted fast backend is a third party with its own
retention policy. Do not point it at a service you haven't approved for that data (the repo owner's rule: warn before sending personal data
off the device).

## Testing and limits

- `pi_pipeline/tests/test_llm_routing.py` covers routing, translation, fallback and fast-only mode with a fake transport; no network is used.
- Not yet run against a real provider or on G2. Unknowns: how well a given free model handles G2's three tools, latency on the Pi, and its limits.
- History is stored in Anthropic's block shape for every backend, so a conversation can switch backends mid-session.
- Intended use with the Petoi AI Head: the head's voice pipeline sends speech to a backend we host, which calls `Conversation`. See
  [`../research/xiaozhi-esp32-review.md`](../research/xiaozhi-esp32-review.md).
