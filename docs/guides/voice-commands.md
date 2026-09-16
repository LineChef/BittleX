# Voice commands -- quick reference

Everything G2 responds to by voice, in three layers:

1. **Local commands** -- matched by exact phrase in `pi_pipeline/voice/commands.py`,
   handled instantly without calling Claude. Safety/session controls, plus a
   couple of live settings toggles (chirps, gir mode, narration verbosity --
   the last two use a small 1-5 level scale, see below).
2. **Conversational skills** -- the physical moves Claude can choose to perform
   mid-conversation via the `perform_skill` tool (`pi_pipeline/voice/skills.py`).
   You don't need the exact wording for these -- just ask naturally ("can you
   sit down?", "go for a walk") and Claude picks the matching skill.
3. **Diagnostics** -- Claude can look up G2's own logs mid-conversation via the
   `diagnostics_query` tool, to answer "why did you fall" / "what's your
   status" instead of guessing. See below.

G2 never moves silently: every recognized local command and every Claude turn
gets a short acknowledgement (a chirp + "heard" cue, then the spoken reply) so
you know it registered before anything happens.

## Local commands

Checked in this priority order -- a higher row always wins if a phrase could
match more than one (e.g. emergency stop beats everything).

| Say | Does | Notes |
|---|---|---|
| "emergency stop", "freeze", "halt", "stop stop stop", "stop moving", "dont move", "hold still", "abort" | **Hard stop, latching.** Cuts all motion now. | Top priority, always wins. Also available offline via `pi_pipeline.app --halt`. |
| "resume", "you can move", "as you were", "unfreeze", "carry on", "at ease", "you can go", "release" | Releases the emergency stop. | Only does something while halted. Also `pi_pipeline.app --release`. |
| "shut down", "shutdown", "power down", "power off", "go dormant", "shut yourself down", "time to shut down" | Lies down, then goes dormant. | Graceful -- not the emergency freeze, not an OS power-off. Wake word brings it back. |
| "come here", "come to me", "over here", "here boy", "walk to me", "come over here" | Walks directly to you. | One-shot directed walk to whoever's nearest. Distinct from "come back" below. |
| "look around", "go ahead and look around", "have a look around", "exploration mode", "explore", "go explore", "go and explore", "check things out", "go for a wander", "wander around" | Arms Tier 1 roam exploring. | Voice-armed only -- G2 won't wander on its own until asked. Leg-budget leashed; comes back on its own when it runs low. |
| "stop exploring", "stop looking around", "stop wandering", "come back", "thats enough", "that will do" | Disarms roam exploring. | |
| "forget that", "forget it", "forget this", "forget what i just said", "forget what i said", "forget that conversation", "forget this conversation", "scratch that", "delete that", "dont remember that", "do not remember that", "dont save that", "do not save that" | Drops everything recorded since the wake word (this session's exchanges + facts). | Privacy control, not a memory it keeps. |
| "go to sleep" | Curls up (`kzz`), camera off, power to headless -- now, overriding a person being present. | Lighter than "shut down": no lie-flat-first settle, and it wakes back up on the wake word or a new interaction rather than staying dormant until told. |
| "enable gir mode", "gir level 4", "disable gir", "gir mode off", ... | Toggles the `gir` character trait (a stylised "chaotic little robot" personality overlay), on a **1-5 level** (`DEFAULT_LEVEL` 2 if you just say "on" with no number). | G2 speaks the level back with what it does, e.g. *"Okay, gir mode on, level 4 of 5: clearly a character but still useful."* Old-style "to 70%" / "to full" phrasing still works too, mapped onto the nearest 1-5 level for the echo-back. |
| "narration level 4", "verbosity level 1", "set narration to level 5" | Sets how much G2 narrates its own actions/reasoning, on a **1-5 level** (3 = default/normal). | G2 speaks the level back with what it does, e.g. *"Okay, narration level 4: detailed -- explain actions and reasoning as you go."* Session-only, like the mood hint -- resets on restart. |
| "turn on your chirps", "enable chirps", "chirps on", "start chirping" | Re-enables chirps, live -- no restart. | |
| "turn off your chirps", "disable chirps", "chirps off", "stop chirping" | Disables chirps, live -- no restart. | The "heard you" ack chirp still fires either way; it's deliberately exempt so a misheard command is never silent. |

A few short reproachful phrases ("leave me alone", "stop it", "be quiet", "shut
up", "go away", "settle down", "calm down", "stop bothering me", ...) aren't
commands -- they just nudge G2's mood toward subdued for a while.

## Conversational skills (ask naturally, Claude picks the move)

| Ask for | Move |
|---|---|
| walk forward | walk forward (continuous gait) |
| walk left / turn left | walk while turning left |
| walk right / turn right | walk while turning right |
| walk backward / back up | walk backward |
| trot | trot forward (faster than walking) |
| crawl | crawl forward, body low |
| sit / sit down | sit |
| stand / stand up | stand in the neutral pose |
| rest / lie down / relax | lie down and relax the servos |
| balance | settle into a low, stable stand (same pose as "stand"; used after a get-up -- not the hind-leg-rearing trick, see `docs/hardware/petoi-skills-survey.md`) |
| stretch | stretch |
| wave / say hi | wave hello with a front leg |
| do push-ups | push-ups |
| scratch | scratch with a hind leg |
| look around / check your surroundings | check-around head scan |
| a beckoning / "come here" gesture mid-conversation | the `come_here` gesture (a wave-over, not a walk -- see note below) |
| go to the zero position | move all joints to zero |

Note: the *local* "come here" phrase above (walking to you) and this
`come_here` *skill* (a beckoning gesture, no walking) are different moves
sharing a name. Because local commands are checked first, saying "come here"
exactly always triggers the walk; the beckoning gesture only comes up if
Claude picks it during a conversation.

Claude will never invoke a calibration or factory-pose command by voice --
those are blocked at the protocol level regardless of what's asked.

## Diagnostics (ask naturally, Claude looks it up)

A third tool, `diagnostics_query` (`pi_pipeline/voice/conversation.py`), lets
Claude read G2's own diagnostic logs to answer questions instead of guessing.
Three topics:

| Ask | Topic | Reads |
|---|---|---|
| "why did you fall / stall / lose the link?", "what happened just now?" | `last_failure` | the most recent failure-taxonomy event in the current/latest session |
| "what's your status?", "how's the session going?" | `summary` | event counts, thermal state, the WARN+ timeline for a session |
| "what features/modes are you running with?" | `status` | `Features.describe()` -- the resolved `G2_FEATURES` state |

**Latency note:** unlike a skill or a fact, a diagnostics answer needs Claude
to actually read the tool's result before it means anything -- and this
codebase's tool-result convention (shared with `perform_skill`/`remember`) is
deliberately deferred to the *next* turn, to avoid a second API round-trip on
every tool call. So the practical shape is: you ask, G2 acknowledges ("let me
check"), and the real answer lands once you say anything next -- not
instantly in the same reply. This is a known tradeoff, not a bug.

**Coverage gap, as of 2026-09:** `last_failure` covers most of the failure
taxonomy (`loop.stall`, `link.lost`, `servo.thermal_cooldown`, `battery.sag`,
`jam.detected`, etc.) but not falls specifically yet -- `RecoveryFSM`
(`pi_pipeline/link/recovery.py`), which classifies a fall, isn't wired into
the live runtime yet, only tested standalone. "Why did you fall" will answer
from whatever *else* is in the log around that time, not the fall itself,
until that integration lands (real fall-recovery testing needs real hardware
anyway).

## Not a voice command, but related

G2 also acts on some things with no phrase to say at all -- the always-on
Tier 0 "attentive" layer (turning toward a sound, following a face with its
head, reacting to something new in view) and idle fidgets/mood-driven chirps
run on their own, no wake word needed. See
[`../capabilities.md`](../capabilities.md) for the full behaviour inventory.
