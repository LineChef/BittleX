---
audience: contributor
kind: reference
---

# Voice

The voice subsystem lets G2 be spoken to and answer, with Claude as the language model and the ability to move in response. It runs on the Pi as the `g2-voice` service.

Behaviour
---------

1. Wake word: G2 listens locally for "gee two". Nothing else happens, and nothing is sent to the network, until it hears it. After a reply the microphone stays open for a short follow-up window, and a question opens a longer one. "Let's talk" starts a conversation mode that listens without the wake word until a quiet gap.
2. Listen: Speech is transcribed on the Pi (Vosk).
3. Local commands: Stop and emergency stop, sleep and shut down, the floor label, "walk for ten seconds", gait switches and more are handled on the Pi with no API call ([Voice commands](../guides/voice-commands.md)).
4. Think: Anything else goes to the Claude API with relevant memory. Claude replies with words and may call a tool: `remember`, `perform_skill` or `await_reply`.
5. Speak: The reply is synthesised on the Pi (Piper), run through the robot-voice effect and played. The next sentence is synthesised while the previous one plays.
6. Act: A `perform_skill` call sends the skill through the serial link.

Interfaces
----------

- Memory: `Memory.recall` before each Claude call and `Memory.record` after ([Memory](memory.md)).
- Actuator: Skills and walks go through the actuator to the [serial link](link.md).
- Sounds: One audio gate lets one sound play at a time, at one global volume.

Parameters
----------

- `G2_FOLLOW_UP_S` and `G2_QUESTION_WINDOW_S`: How long the microphone stays open after a reply and after a question (3 s each)
- `G2_WAKE_MIN_CONF`: The wake phrase confidence below which a trigger is ignored (0.6)
- `G2_VOLUME`: The one volume for every sound, speech and buzzer included (65% of maximum, capped at 75%)
- `G2_MIC_GAIN`: Digital microphone gain (×20)
- `G2_SLEEP_AFTER_S`: Seconds at rest before G2 sleeps (300)
- `G2_EXPLORE_REQUEST` and `G2_EXPLORE_ASK_AFTER_S`: Whether G2 asks to explore after idling, and after how many seconds (on, 180)

Constraints
-----------

- API use: Claude calls are used sparingly, because they cost money. Everything that can be done locally on the Pi is.
- No self-hearing: The wake detector and the command window ignore audio while G2 speaks and for 0.8 s afterwards.
- One microphone stream: It is opened once for the life of the process and never closed.
- Fragments: A turn of one or two filler words right after the wake word is dropped with no reply and no saved record.
- Stop phrases: A stop counts only when the whole sentence is the phrase and every word is above the confidence floor.

Failure handling
----------------

- Dead camera or microphone reader: A supervisor restarts it with backoff.
- Service crash: systemd restarts the service one second after a failure.
- No network: Local commands still work, and Claude replies are unavailable.

Verification
------------

- `python -m pi_pipeline.voice --mode text` runs a conversation with no audio hardware.
- `python -m pi_pipeline.voice.check_audio mic 15` measures the microphone with `g2-voice` stopped.
