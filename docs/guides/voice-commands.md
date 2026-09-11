# Voice commands -- quick reference

Everything G2 responds to by voice, in two layers:

1. **Local commands** -- matched by exact phrase in `pi_pipeline/voice/commands.py`,
   handled instantly without calling Claude. Mostly safety/session controls.
2. **Conversational skills** -- the physical moves Claude can choose to perform
   mid-conversation via the `perform_skill` tool (`pi_pipeline/voice/skills.py`).
   You don't need the exact wording for these -- just ask naturally ("can you
   sit down?", "go for a walk") and Claude picks the matching skill.

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
| "enable gir mode", "turn on gir", "gir mode on", "set gir to 70", "disable gir", "gir mode off", ... | Toggles the `gir` character trait (a stylised "chaotic little robot" personality overlay), optionally at a stated intensity. | `to <N>` / `at <N>%` / "to full"/"half"/"low"/"high" all parse as a level. |

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
| balance | stand and actively balance |
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

## Not a voice command, but related

G2 also acts on some things with no phrase to say at all -- the always-on
Tier 0 "attentive" layer (turning toward a sound, following a face with its
head, reacting to something new in view) and idle fidgets/mood-driven chirps
run on their own, no wake word needed. See
[`../capabilities.md`](../capabilities.md) for the full behaviour inventory.
