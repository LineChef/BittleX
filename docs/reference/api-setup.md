# Anthropic API setup checklist

Two layers: account-side limits (the real hard stop — enforced by Anthropic, not
by G2's own code, so a bug in G2 can't get around it) and G2-side limits (faster,
local, and can warn *before* the hard stop is hit). Do both.

## Account side (console.anthropic.com) — one-time, do this first

- [ ] **Create a dedicated API key for G2**, separate from any other project/key
      you have. Isolates its spend and lets you revoke or re-cap just this key
      without touching anything else.
- [ ] **Set a monthly spend limit** on the key / workspace (Console → Billing or
      Limits). This is the actual ceiling — once hit, calls fail instead of
      racking up charges, regardless of anything G2's code does or doesn't do.
- [ ] **Enable usage alert emails** at a threshold (e.g. 50% / 80%) so you hear
      about rising spend before the limit bites.
- [ ] If available on your plan, consider **prepaid credits instead of
      auto-reload** — spend literally can't exceed what's loaded.
- [ ] Put the key in the gitignored `.env` as `ANTHROPIC_API_KEY=` — **never** in
      a tracked file (see the repo-privacy rules; the pre-commit hook doesn't
      scan for API-key-shaped strings, so this one's on you).
- [ ] **Bookmark the key's console page** so revoking a lost/compromised key is a
      2-minute job, not a search (ties to the lost-device hardening item in
      `pi-set-up.md` §9).

## G2 side — local, faster, and can warn ahead of time — NOT YET BUILT

Two independent guardrails, because they catch different failures:

- [ ] **Call-rate limiter** — cap calls/minute (e.g. `G2_MAX_CALLS_PER_MIN`).
      Catches a *bug* (wake-word false-trigger loop, a retry storm) in seconds,
      before it's spent real money. Doesn't need to know cost at all.
- [ ] **Local usage tracker** — every API response reports its exact token usage
      (`usage.input_tokens` / `usage.output_tokens`); log each call + a running
      daily/monthly total to a local gitignored store (not the repo, not synced
      — same pattern as the memory DB).
- [ ] **Price-per-token config**, filled in by hand from the current pricing
      page (`G2_INPUT_COST_PER_MTOK`, `G2_OUTPUT_COST_PER_MTOK`) — tracked in
      tokens for certain, estimated to $ from a knob you set, not a hardcoded
      number that could go stale.
- [ ] **Budget caps** (`G2_DAILY_BUDGET_USD`, `G2_MONTHLY_BUDGET_USD`). Once
      crossed, G2 **refuses further API calls itself** and says so out loud
      ("I can't chat right now, I've hit today's budget") — fails safe, locally,
      without waiting on Anthropic's own limit.
- [ ] **Early warning** (the new ask) — a configurable threshold *below* the hard
      cap (`G2_BUDGET_WARN_PCT`, default ~0.8). The first time a period crosses
      it, G2 says/logs a warning once — not every subsequent call, so it doesn't
      nag — e.g. "heads up, I'm at 80% of today's chat budget." Gives you a
      heads-up before the hard refusal ever interrupts a conversation, and
      doesn't depend on Anthropic's account-wide alert email (which is slower
      and not G2-specific).
- [ ] `python -m pi_pipeline.voice usage` (or similar) — check current spend /
      remaining budget anytime, without opening the console.
- [ ] **Verify it end-to-end** before trusting it: temporarily set a tiny budget,
      make a couple of calls, confirm the warning fires once, confirm the hard
      refusal fires next and G2 fails gracefully (a spoken message, not a
      crash), then restore the real budget.

## Status

Account-side: not yet done (do when the API key is first set up). G2-side:
specified above, not yet implemented — say the word and it gets built into
`pi_pipeline/voice/`.
