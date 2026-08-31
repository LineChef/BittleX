"""Entrypoint for the voice loop:  python -m pi_pipeline.voice

    --mode text        type instead of speaking; G2 replies via macOS `say`
    --mode voice       wake word + mic (Vosk) + Piper TTS  (needs audio deps + models)
    --actuator mock    log skill commands (default)
    --actuator serial  send them to the BiBoard over serial  (on hardware)
"""
from __future__ import annotations

import argparse
import logging

from ..config import settings
from ..memory.memory import Memory
from .actuator import make_actuator
from .conversation import Conversation
from .cues import LogCue
from .loop import VoiceLoop
from .stt import make_stt
from .tts import make_tts
from .wake_word import make_wake_word


def main() -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.voice")
    ap.add_argument("--mode", choices=["text", "voice"], default="text")
    ap.add_argument("--actuator", choices=["mock", "serial"], default="mock")
    ap.add_argument("--tts", choices=["auto", "mac", "piper", "print"], default="auto")
    ap.add_argument("--no-memory", action="store_true", help="run without persistent memory")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    voice = args.mode == "voice"
    tts_mode = {"auto": "piper" if voice else "mac", "mac": "mac",
                "piper": "piper", "print": "print"}[args.tts]

    memory = None
    if settings.memory_enabled and not args.no_memory:
        memory = Memory(settings)

    loop = VoiceLoop(
        wake_word=make_wake_word(
            "vosk" if voice else "none",
            vosk_model_path=settings.vosk_model_path,
            phrase=settings.wake_word,
        ),
        stt=make_stt(
            "vosk" if voice else "text",
            vosk_model_path=settings.vosk_model_path,
            silence_s=settings.stt_silence_s,
        ),
        conversation=Conversation(settings),
        tts=make_tts(tts_mode, piper_model_path=settings.piper_model_path),
        actuator=make_actuator(
            args.actuator, port=settings.serial_port, baud=settings.serial_baud
        ),
        cue=LogCue(),
        memory=memory,
    )
    try:
        loop.run_forever()
    finally:
        if memory:
            memory.close()


if __name__ == "__main__":
    main()
