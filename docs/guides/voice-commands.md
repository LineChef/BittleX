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
| "walk for ten seconds", "walk forward for 25 seconds", "walk for a minute", "walk 15 seconds", "start walking", "walk forward" | Walks straight ahead with the learned gait for that long (a bare "walk forward" = 10 s, at most 60 s), **no API call**. | Added 2026-10-09 (the Claude round trip for it was unreliable). Numbers as words or digits. Anything longer ("walk for eight seconds and then wave", "walk over to the kitchen") still goes to Claude; "walk to me" is come-here. |
| "look around", "go ahead and look around", "have a look around", "exploration mode", "explore", "go explore", "go and explore", "check things out", "go for a wander", "wander around" | Arms Tier 1 roam exploring. | Voice-armed only -- G2 won't wander on its own until asked. Leg-budget leashed; comes back on its own when it runs low. |
| "stop exploring", "stop looking around", "stop wandering", "come back", "thats enough", "that will do" | Disarms roam exploring. | |
| "forget that", "forget it", "forget this", "forget what i just said", "forget what i said", "forget that conversation", "forget this conversation", "scratch that", "delete that", "dont remember that", "do not remember that", "dont save that", "do not save that" | Drops everything recorded since the wake word (this session's exchanges + facts). | Privacy control, not a memory it keeps. |
| "go to sleep" | Curls up (`kzz`), camera off, power to headless -- now, overriding a person being present. | Lighter than "shut down": no lie-flat-first settle, and it wakes back up on the wake word or a new interaction rather than staying dormant until told. |
| "enable gir mode", "gir level 4", "disable gir", "gir mode off", ... | Toggles the `gir` character trait (a stylised "chaotic little robot" personality overlay), on a **1-5 level** (`DEFAULT_LEVEL` 2 if you just say "on" with no number). | G2 speaks the level back with what it does, e.g. *"Okay, gir mode on, level 4 of 5: clearly a character but still useful."* Old-style "to 70%" / "to full" phrasing still works too, mapped onto the nearest 1-5 level for the echo-back. |
| "narration level 4", "verbosity level 1", "set narration to level 5" | Sets how much G2 narrates its own actions/reasoning, on a **1-5 level** (3 = default/normal). | G2 speaks the level back with what it does, e.g. *"Okay, narration level 4: detailed -- explain actions and reasoning as you go."* Session-only, like the mood hint -- resets on restart. |
| "turn on your chirps", "enable chirps", "chirps on", "start chirping" | Re-enables chirps, live -- no restart. | |
| "turn off your chirps", "disable chirps", "chirps off", "stop chirping" | Disables chirps, live -- no restart. | The "heard you" ack chirp still fires either way; it's deliberately exempt so a misheard command is never silent. |
| "the floor is tile", "we're on hardwood", "this is a tile floor", "set the floor to carpet" (tile, hardwood, carpet, laminate, linoleum, concrete, rug, mat) | Sets the floor label that every run log records (`g2floor`), with no API call. **"This is a ..." only counts as a floor when the word *floor* ends it** (otherwise it is the naming command and takes a picture). Say it at the start of a session and when G2 moves to another floor. | G2 says *"Okay, the floor is tile."* Works in normal voice mode and in exploration sessions. |
| "what floor are you on", "which floor" | Asks which floor label is set. | G2 reads it back, or says he does not know. |

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
| nod | nod — yes, agreement, understanding (`knd`) |
| shake head | shake the head — no, disagreement, confusion (`kwh`) |
| look around / check your surroundings | check-around head scan (`kck`; also Claude's "thinking" reaction) |
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

## The BiBoard's own voice module (heard by the board, not the Pi)

G2's BiBoard has a separate offline voice module with **no wake word**: it listens all the time and acts on its fixed phrases (40 in two languages, plus up to 10 you record in learning mode). It
does not go through the Pi's voice loop, so a phrase meant for the Pi can also trigger it. Details and the incident history: [`../hardware/petoi-firmware-reference.md`](../hardware/petoi-firmware-reference.md).

| Say | What it does | Serial equivalent |
|---|---|---|
| **"bing bing"** | Switches the module to **English** (use it when the module has fallen back to Chinese and G2 ignores English commands) | `XAa` |
| "play sound" | Liveness test (replies with a Do-Re-Mi tone, works in either language) and turns the module's basic commands back on after "be quiet" | -- |
| "be quiet" | Mutes the module: it ignores basic commands such as "rest" until "play sound" | -- (do NOT use `Xa` / `XAd`, they silently break the module) |
| "rest" | One of the module's fixed commands (G2 lies down). "stop" is not one | -- |

Other serial settings for the same module (sent by the Pi or `check_serial`, never spoken): `XAb` Chinese, `XAc` enable, `XAe` learning mode. If it answers "ok" but the body does not move, send `XA`
and check the dial on the hat is on "Voice Command". Recovery when it is stuck defaulting to Chinese: `XAc`, `XAb`, `XAa` about 1.2 s apart (or say "bing bing").

## Not a voice command, but related

G2 also acts on some things with no phrase to say at all -- the always-on
Tier 0 "attentive" layer (turning toward a sound, following a face with its
head, reacting to something new in view) and idle fidgets/mood-driven chirps
run on their own, no wake word needed. See
[`../capabilities.md`](../capabilities.md) for the full behaviour inventory.


## The three sounds of an exchange (2026-10-09)

| Sound | Means |
|---|---|
| **beep** (one short bright note) | he heard the wake word and is listening |
| **boop** (one lower, rounder note) | he thinks you have finished speaking and has your words |
| **two falling notes** | the follow-up window ended: he has stopped listening (say the wake word again) |

On the speaker (`voice/prompt_tones.py`) and, without a speaker, as buzzer beeps (`voice/cues.py`, `LOW_CUES`). `G2_CUE_STAGES` picks which are on (default `awake,captured,closed`).


## Switching gait (2026-10-09)

| Say | Does |
|---|---|
| "hi step" / "high step" / "step mode" | switches to the hi-step gait. With today's V4 this is the scripted hsF gait without a learned correction (G2 says so: slow, experimental); a policy trained for the mode would use its learned correction. |
| "walk normally" / "walk mode" / "normal mode" / "normal walk" | back to the normal walk (the V4 policy). |

Works in the voice loop and during an exploration session (one shared state, `gait/gait_mode.py`); a short double beep plays when the gait really switches. The switch takes effect at the next walk or exploration leg.
