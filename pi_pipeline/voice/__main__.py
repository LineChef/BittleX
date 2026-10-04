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
from ..diag import diag
from ..features import features, log_summary
from ..memory.memory import Memory
from ..util.disk import start_disk_watch
from .actuator import make_actuator
from .conversation import Conversation
from .cues import BuzzerCue, LogCue
from .loop import VoiceLoop
from .stt import make_stt
from .tts import make_tts
from .wake_word import make_wake_word


def main() -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.voice")
    ap.add_argument("--mode", choices=["text", "voice"], default="text")
    ap.add_argument("--actuator", choices=["mock", "serial"], default="mock")
    ap.add_argument("--max-gait-s", type=float, default=None,
                    help="serial actuator: auto-stop a looping gait (walk/trot/crawl) after this many seconds; "
                         "0 = off. Default: the G2_MAX_GAIT_S setting (off unless set in .env)")
    ap.add_argument("--tts", choices=["auto", "mac", "piper", "print"], default=None,
                    help="speech output; default: the G2_TTS setting (auto)")
    ap.add_argument("--no-memory", action="store_true", help="run without persistent memory")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    log_summary()
    start_disk_watch(settings.disk_warn_pct)

    _lvl, _msg = settings.api_key_expiry_status()
    if _msg:
        _log = logging.getLogger("g2.voice")
        (_log.error if _lvl == "expired" else _log.warning)(_msg)

    with diag.session("voice", extra={"mode": args.mode, "actuator": args.actuator}):
        voice = args.mode == "voice"
        if voice and not features.mic:
            logging.getLogger("g2.voice").warning(
                "features: mic is off -- falling back to --mode text")
            voice = False
        tts_mode = {"auto": "piper" if voice else "mac", "mac": "mac",
                    "piper": "piper", "print": "print"}[args.tts or settings.tts_mode]
        if not features.tts:
            tts_mode = "print"
        use_wake = voice and features.wake_word

        memory = None
        if settings.memory_enabled and not args.no_memory and features.memory:
            memory = Memory(settings)

        actuator = make_actuator(
            args.actuator, port=settings.serial_port, baud=settings.serial_baud,
            max_continuous_s=args.max_gait_s,
        )
        # buzzer cues on the real robot (the sound_cues feature flag turns them off)
        if args.actuator == "serial" and features.sound_cues:
            stages = tuple(x.strip() for x in settings.cue_stages.split(",") if x.strip())
            cue = BuzzerCue(actuator, shift=settings.buzzer_shift, length=settings.buzzer_length,
                            stages=stages, volume=settings.buzzer_volume)
            cue.prime()
        else:
            cue = LogCue()

        loop = VoiceLoop(
            wake_word=make_wake_word(
                "vosk" if use_wake else "none",
                vosk_model_path=settings.vosk_model_path,
                phrase=settings.wake_word,
            ),
            stt=make_stt(
                "vosk" if voice else "text",
                vosk_model_path=settings.vosk_model_path,
                silence_s=settings.stt_silence_s,
            ),
            conversation=Conversation(settings),
            tts=make_tts(tts_mode, piper_model_path=settings.piper_model_path,
                        style=settings.voice_style),
            actuator=actuator,
            cue=cue,
            memory=memory,
            follow_up_s=settings.follow_up_s if voice else 0.0,
            question_window_s=settings.question_window_s if voice else 0.0,
        )
        try:
            loop.run_forever()
        finally:
            if memory:
                memory.close()


if __name__ == "__main__":
    main()
