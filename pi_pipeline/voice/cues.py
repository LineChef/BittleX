"""State cues for the voice loop: listening / thinking / speaking.

Claude round-trips have noticeable latency on this hardware, so a cue tells the
user which stage they're in. `LogCue` is enough on a dev machine; on the robot
this grows a buzzer-pattern and/or posture implementation (a Phase 7 task).
"""
from __future__ import annotations

import logging
from typing import Literal, Protocol

Stage = Literal["idle", "awake", "listening", "captured", "heard", "thinking", "speaking", "closed", "gait_switch"]

log = logging.getLogger("g2.cue")


class Cue(Protocol):
    def set(self, stage: Stage) -> None: ...


class LogCue:
    def set(self, stage: Stage) -> None:
        log.info("[%s]", stage)


# Cue melodies as (note, duration divisor); notes are C3 = 14 semitone numbers, and the buzzer reproduces 1-35 (low is loudest).
# On 2026-10-04 notes 26/30 were faint, +7 and +14 semitones were not heard at all, and the pair 4 and 8 was the loudest of a sweep.
# "thinking" is the acknowledgement for a command that goes to Claude: a low rising two-note blip. (A bosun's-call style whistle was
# drafted and dropped for now; see docs/research/buzzer-sounds.md.)
LOW_CUES: dict[str, list[tuple[int, int]]] = {
    "awake": [(10, 4)],                # the wake word was heard: ONE short beep (user, 2026-10-09; used when there is no speaker)
    "captured": [(4, 3)],              # he thinks you have finished speaking and has your words: ONE lower "boop"
    "closed": [(8, 4), (4, 3)],
    "gait_switch": [(10, 8), (10, 8)],  # a short double beep: he is switching gait ("hi step" / "walk normally")        # the follow-up window ended, he has stopped listening: two falling notes
    "listening": [(8, 3), (8, 3)],     # two equal beeps: ready, say your command
    "thinking": [(4, 4), (9, 2)],      # a low rising pair: got your words, asking Claude
    "heard": [(4, 3), (8, 3)],         # quick "got it" for a recognised local command
}

DEFAULT_STAGES = ("awake", "captured", "closed", "gait_switch")          # the sound is the wake chime, right after the wake word (2026-10-07); API calls have their own tone (voice/api_tone.py)


class SpeakerCue:
    """Plays an acknowledgement tone through the Pi's speaker on the chosen stages, and logs every stage. `tone` names the sound:
    `short_tone` (default, one short blip) or `star_trek_whistle`. Replaces the buzzer blip for those stages, since the buzzer can
    only beep in separate notes."""

    def __init__(self, inner: Cue | None = None, *, stages=DEFAULT_STAGES, peak: float | None = None, player=None,
                 tone: str = "short_tone"):
        from . import short_tone, star_trek_whistle, wake_chime

        module = {"short_tone": short_tone, "star_trek_whistle": star_trek_whistle}[tone]
        self._inner = inner or LogCue()
        self._stages = set(stages)
        self._play = player or (lambda: module.play(peak if peak is not None else module.DEFAULT_PEAK))
        # `wait=True`: the tone plays to its end before the loop goes on, because the next sound (the thinking tone, the spoken reply) starts at once and a second sounddevice play cuts the first one off -- the boop was never heard (user, 2026-10-10).
        # the three exchange stages each have their own sound whatever `tone` the others use (user, 2026-10-09): beep = listening, boop = your words are captured, close = he stopped listening
        from . import prompt_tones
        pk = lambda default: peak if peak is not None else default                     # noqa: E731
        self._stage_play = {} if player else {
            "awake": lambda: prompt_tones.play_beep(pk(prompt_tones.DEFAULT_PEAK)),
            "captured": lambda: prompt_tones.play_boop(pk(prompt_tones.DEFAULT_PEAK), wait=True),
            "closed": lambda: prompt_tones.play_close(pk(prompt_tones.DEFAULT_PEAK), wait=True),
            "gait_switch": lambda: prompt_tones.play_double(pk(prompt_tones.DEFAULT_PEAK), wait=True),
        }

    def set(self, stage: Stage) -> None:
        self._inner.set(stage)
        if stage in self._stages:
            self._stage_play.get(stage, self._play)()


def chunk_notes(notes: list[tuple[int, int]], max_chars: int = 60) -> list[list[tuple[int, int]]]:
    """Split a melody so each serial token stays short (a long token risks overflowing the board's command buffer)."""
    chunks, cur, size = [], [], 1
    for tone, dur in notes:
        n = len(f" {tone} {dur}")
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur, size = [], 1
        cur.append((tone, dur))
        size += n
    if cur:
        chunks.append(cur)
    return chunks


class BuzzerCue:
    """Logs each stage and also beeps it on G2's buzzer, so you can hear that G2 heard the wake
    word, got your command, or recognised a local command. Melodies are the ones in
    `behavior.chirps` (listening = two sharp beeps, thinking = rising "?", heard = quick blip).
    A beep failing never breaks the loop."""

    def __init__(self, actuator, inner: Cue | None = None, *, shift: float = 0.0, length: float = 1.0,
                 stages=DEFAULT_STAGES, volume: int = 0):
        self._act = actuator
        self._inner = inner or LogCue()
        self._shift = int(round(shift))
        self._length = length
        self._stages = set(stages)
        self._volume = volume

    def prime(self) -> None:
        """Set the buzzer volume once (call at startup). 0 leaves the board's volume alone."""
        if not self._volume:
            return
        from ..link import opencat

        send = getattr(self._act, "send_token", None)
        if send is not None:
            try:
                send(opencat.buzzer_volume(self._volume))
            except Exception:  # noqa: BLE001
                log.debug("setting the buzzer volume failed", exc_info=True)

    def set(self, stage: Stage) -> None:
        self._inner.set(stage)
        if stage not in self._stages:
            return
        send = getattr(self._act, "send_token", None)
        if send is None:
            return
        try:
            for token in self._tokens(stage):
                send(token)
        except Exception:  # noqa: BLE001 -- a cue must never take the loop down
            log.debug("buzzer cue %r failed", stage, exc_info=True)

    def _tokens(self, stage: Stage) -> list[str]:
        """The `b...` tokens for a stage: its melody from LOW_CUES, raised by `shift` semitones and made `length` times
        longer (both default to no change), split into short tokens."""
        from ..link import opencat

        notes = LOW_CUES.get(stage)
        if not notes:
            return []
        # `dur` is a divisor of one second (4 = a quarter second), so a LONGER note is a SMALLER number
        shaped = [(max(1, tone + self._shift), max(1, int(dur / self._length + 0.5))) for tone, dur in notes]
        return [opencat.beep(c) for c in chunk_notes(shaped)]
