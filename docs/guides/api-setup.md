---
audience: builder
kind: guide
---

# Setting up the Claude API key and spending limits

G2 talks through the Claude API, which bills per use. This page covers two layers of protection: limits set in the Anthropic console, and limits inside G2's own software. The console limits are the hard stop, because Anthropic enforces them and a bug in G2 cannot get around them. G2's own limits are faster, and they warn before the hard stop is reached. Set up both.

In the Anthropic console
------------------------

Do these once, before the key is first used.

1. Create a dedicated API key for G2: Keep it separate from any other project's key. That isolates G2's spending and allows revoking or re-capping this key alone.
2. Set a monthly spend limit on the key or workspace (Console, Billing or Limits). This is the real ceiling. Once it is reached, calls fail instead of running up charges.
3. Turn on usage alert emails at a threshold such as 50% and 80%, so rising spend is noticed before the limit is reached.
4. Consider prepaid credits instead of auto-reload where the plan offers them. Spend then cannot exceed what is loaded.
5. Store the key in the gitignored `.env` file as `ANTHROPIC_API_KEY=`. Never put it in a tracked file. The pre-commit hook does not scan for key-shaped strings.
6. Bookmark the key's console page so revoking a lost or exposed key takes minutes.
7. Record the expiry, if the key has one. Add `ANTHROPIC_API_KEY_EXPIRES=YYYY-MM-DD` to `.env`. G2 logs a warning as the date approaches (`G2_API_KEY_EXPIRY_WARN_DAYS`, default 30) and an error once it has passed, so an expired key is never a silent non-reply. Update both the console expiry and this date when the key is rotated.

Inside G2
---------

### Usage tracking

Every API call is logged with its exact token count in a gitignored file under `~/.local/share/g2/` (`voice/api_log.py`). `g2api [hours]` shows calls, tokens and an approximate cost by source. `python -m pi_pipeline.voice.usage` prints a per-day report that counts each turn and retry.

Dollars are estimated from two prices set in `.env`: `G2_PRICE_IN_PER_MTOK` and `G2_PRICE_OUT_PER_MTOK`. They are filled in by hand from the current pricing page, so a price change never leaves a stale figure in the code.

### Clear spoken messages when the API refuses

Every limit follows one rule: warn before it is hit, and say or log clearly when it is hit. A failure is never silent and never a raw error. G2 classifies what the API returns and speaks a plain line for each case:

- Authentication error (revoked, expired or wrong key): What happens: No retry.; Spoken line (setting that changes it): `G2_SPEECH_API_AUTH`, by default "I can't reach my brain right now -- my API key may be invalid or expired."
- Rate limit: What happens: Backs off and retries up to three times.; Spoken line (setting that changes it): `G2_SPEECH_API_RATE`
- Billing or quota error: What happens: No retry.; Spoken line (setting that changes it): `G2_SPEECH_API_BILLING`
- Anything else: What happens: The voice loop stays alive.; Spoken line (setting that changes it): A generic "I glitched."

The voice loop catches the error, speaks the line and logs the failure kind. The phrases can all be overridden in `.env`.

### Not built yet

- A **call-rate limiter** (for example `G2_MAX_CALLS_PER_MIN`) would catch a bug such as a wake-word false-trigger loop or a retry storm within seconds, without needing to know any cost.
- Local budget caps (`G2_DAILY_BUDGET_USD`, `G2_MONTHLY_BUDGET_USD`) would make G2 refuse further calls once crossed and say so, without waiting for Anthropic's own limit.
- An **early warning** below the cap (`G2_BUDGET_WARN_PCT`, about 0.8) would speak once when a period crosses the threshold.

Once these exist, they should be checked end to end: set a tiny budget temporarily, confirm the warning and the refusal both fire and read clearly, force a rate-limit and a billing error, confirm each gives a clear message, then restore the real budget.
