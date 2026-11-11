---
audience: visitor
kind: overview
---

# What G2 can do

This page lists G2's abilities in plain terms, grouped by what a person would notice. Each entry says whether the ability works today or is only partly proven. For how each part works, see [How it works](how-it-works.md). For the current state of the hardware and open problems, see [Current status](STATUS.md).

**Labels used below**

- **Working.** Runs today on G2 or in simulation.
- **Built, not yet proven.** The code is finished and tested against stand-ins, but it has not yet been exercised on the real robot.
- **Parked.** Investigated, with the outcome recorded, and not being worked on now.

## Moving

- **Learned walking gait**: State: Working on hardwood; Notes: A trained policy adds small corrections to Petoi's scripted walk. See [Walking policy](rl/walking-policy.md).
- **Turning, backing up, sitting, resting**: State: Working; Notes: Played by the control board, with eased starts so G2 does not jerk or tip.
- **Built-in tricks**: State: Working, with exceptions; Notes: About twenty Petoi skills have friendly names (bow, nod, stretch and more). Wave, scratch, shake paw, high five and hop are refused because they tip G2 over. See [Disabled moves](hardware/disabled-moves.md).
- **Carpet mode**: State: Built, not yet proven; Notes: "Carpet mode" switches to Petoi's own carpet gait. No learned gait walks well on carpet.
- **Stepping over ledges**: State: Parked; Notes: No trained policy crosses steps above about 0.3 in.

## Talking and listening

- **Wake word**: State: Working; Notes: G2 listens locally for "Gee Two". Nothing is recorded or sent before that.
- **Spoken commands**: State: Working; Notes: Stop, sleep, shut down, "walk for ten seconds", gait and floor settings. They run on the Pi with no network call. See [Voice commands](guides/voice-commands.md).
- **Conversation with Claude**: State: Working; Notes: Anything that is not a local command goes to Claude, which can reply, move G2 and save facts.
- **Robot voice and sounds**: State: Working; Notes: Speech passes through a robot-voice effect. Short sounds signal the wake word, pictures, gait changes and warnings. One volume setting controls all of them.
- **Swappable language model**: State: Built, not yet proven; Notes: A cheaper or free model can replace or share the work. See [Swappable LLM](guides/swappable-llm.md).

## Remembering

- **Lasting facts**: State: Working; Notes: G2 saves facts worth keeping, such as names and preferences.
- **Recall of past conversations**: State: Working; Notes: Before each reply, G2 looks up older exchanges related to what was just said.
- **Tidying**: State: Working; Notes: When idle, G2 merges duplicate facts and drops trivial ones.
- **Reflection on a session**: State: Parked; Notes: A short recap is written after each session. A deeper reflection step is switched off.

## Seeing

- **Object detection**: State: Working; Notes: A custom model runs on the camera itself and reports what it sees.
- **"What do you see"**: State: Working; Notes: One picture goes to Claude along with the camera's labels, and G2 describes the scene aloud.
- **Wall avoidance**: State: Working, needs recalibration; Notes: G2 estimates the distance to a wall from a picture and turns away.
- **Finding a ball**: State: Working; Notes: A colour finder locates a green ball, and the claw camera helps line up a punt.
- **Recognising specific things**: State: Built, not yet proven; Notes: G2 compares photo crops with a library to tell "the same thing again" from "something new".

## Acting on its own

- **Looking around while still**: State: Working; Notes: G2 turns toward sounds and follows a person with its gaze. It does not walk in this mode.
- **Exploring a room**: State: Working in a small room; Notes: After a spoken go-ahead, G2 walks, turns away from walls, reacts to bumps, takes pictures and narrates. See [Exploration mode](guides/exploration-mode.md).
- **Goals**: State: Working, mixed results; Notes: G2 is given a goal such as punting a ball, makes up to ten attempts and adjusts its approach between them. See [Goals](guides/goals.md) and [Punt](guides/punt.md).
- **Resting and sleeping**: State: Working; Notes: After a quiet stretch G2 sits, lies down and then sleeps. Sleep lowers the Pi's power use and turns the camera off.
- **Personality**: State: Working; Notes: Traits such as curiosity and playfulness, and a mood that follows recent interaction, shape both the replies and the behaviour.

## Staying safe

- **Emergency stop**: State: Working; Notes: A spoken "emergency stop", a command-line halt or a signal stops everything. See [Operating G2](guides/operating-g2.md).
- **Refusing dangerous moves**: State: Working; Notes: The serial link blocks moves that tip G2 over, and commands that would erase calibration.
- **Servo heat protection**: State: Working; Notes: An estimate of servo heat slows or stops walking before the servos overheat.
- **Fall and stall detection**: State: Working; Notes: G2 notices tipping and stalled walks, and stops or recovers.
- **Battery warnings**: State: Working; Notes: G2 warns by voice when its pack or the Pi's pack runs low.
- **Logging**: State: Working; Notes: Every session writes a structured log with a short "black box" history, so a failure can be examined afterwards. See [Diagnostics](hardware/diagnostics.md).

## Neck attachments

G2 can wear a Petoi AI Head or a claw arm, or nothing. One setting records what is fitted. It selects the walking policy saved for that attachment, checks the firmware and switches the right skills on or off. See [Attachments](guides/attachments.md).

## Tools for people running G2

- Shell helpers for the common tasks, listed in the [Cheat sheet](guides/cheatsheet.md) and [Shell helpers](guides/shell-helpers.md).
- A guided hardware bring-up and a readiness checklist. See [Bring-up sequence](guides/bring-up-sequence.md).
- A review page for naming the pictures G2 takes while exploring.
- Reports on each session: walks, speech delay, wake-word triggers, API use and problems.
