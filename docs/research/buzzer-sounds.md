# Buzzer sounds for G2 — what exists and what to build

Researched 2026-10-04 for the voice cues (acknowledgement chirp) and the behavior-runtime chirps.

## What the board can do
- One serial token, `b`, plays melodies: pairs of **(note, duration)**, chained in one command. **Note** is a semitone number with C3 = 14 and
  C4 = 26; **1-35 is the usable range** and rests are 0 or -1. **Duration** is a divisor of one second (`b14 4` = 1/4 s), not milliseconds, so a
  longer note is a smaller number.
  Source: [Petoi melody creation guide](https://guide.petoi.com/applications/melody-creation).
- Petoi's [serial protocol page](https://docs.petoi.com/apis/serial-protocol) also lists `b` followed by 1-10 as a **volume** setting, a bare `b`
  as a mute toggle, a binary variant `B`, and `u` as a cat-sound command listed for Nybble. The melody guide does not mention volume; whether `b10` works on this
  firmware (B10_260527) is unconfirmed — it echoes `b` and was being listened-for on 2026-10-04. Never send a bare `b`.
- Measured on G2's buzzer 2026-10-04: notes 26 and 30 are faint, notes 33+ were not heard at all, and the loudest was the lowest pair tried
  (notes 4 and 8). So everything we want to hear should live low, well below the 1-35 ceiling.

## Is there a ready-made library of chirps?
- **No built-in Petoi sound library.** The guide has only the format and one worked example (Twinkle, Twinkle). Petoi's curriculum has a
  [Singing Bittle X project](https://learning.petoi.com/Petoi%20Web-based%20Curriculum/Project%20Singing%20Bittle%20X%20-%20Train%20Bittle%20X%20to%20show%20%202dd7eabef82481f19d54e5aca6c936d8)
  built around moods and singing, and the guide notes an AI can generate a melody sequence, but neither ships a catalogue.
- **RTTTL (ringtone) is the big ready-made source.** It is a plain-text melody format with large public collections of ringtones, and
  Arduino libraries play it ([AnyRtttl](https://reference.arduino.cc/reference/en/libraries/anyrtttl),
  [PlayRtttl](https://arduino.cc/reference/en/libraries/playrtttl),
  [NonBlockingRTTTL](https://github.com/end2endzone/nonblockingrtttl),
  [Melody Player](https://reference.arduino.cc/reference/en/libraries/melody-player)). Those libraries drive a buzzer pin directly, so they
  do not help here: the buzzer belongs to the BiBoard and we only send it `b` tokens. What we can reuse is the **format and the songs**: a small
  RTTTL parser that converts note names to semitone numbers and durations to divisors, then transposes the result into notes 1-35.
- **R2-D2 / emotional-robot sounds** are design references, not libraries: the
  [R2D2 sound generator](https://instructables.com/R2D2-Sound-Generator),
  an [Arduino forum thread](https://forum.arduino.cc/t/r2d2-sounds-via-tone-command/52697) and a Politecnico di Milano
  [emotional sounds project](https://pii.deib.polimi.it/emotional-sound-like-r2d2-or-bb8/) describe fast glides, trills and
  rising/falling contours for moods. They suit our `ChirpMood` set (happy, confused, alert, sleepy, question, greeting, ack).

## Plan, when we want more sounds
1. Write the RTTTL converter (~40 lines, in `pi_pipeline/link/`), with the transpose-into-1-35 step and a token chunker (already have one in `voice/cues.py`).
2. Curate a handful of melodies from public RTTTL collections as named cues; check licensing for anything we commit.
3. Move the seven behavior chirps (`behavior/chirps.py`) into the audible low range and give each a distinct contour.

The acknowledgement cue in use is the low rising two-note pair (`voice/cues.py`, `LOW_CUES["thinking"]`: note 4 then 9). A bosun's-call style rising
whistle (a fast glide from note 8 up to 20, a warble at 23/21, a drop, about 0.9 s) was drafted and set aside; the buzzer cannot whistle, so it would be
the gesture rather than the timbre, and a cue longer than about a second risks delaying the next command since the board plays a beep before reading more
serial. Revisit it when we pick the larger sound set.
