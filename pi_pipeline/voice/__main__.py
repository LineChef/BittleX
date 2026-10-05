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
from .cues import BuzzerCue, LogCue, SpeakerCue
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
        # acknowledgement tone (the sound_cues feature flag turns all cues off): the whistle through the speaker when there
        # is one, else the buzzer cues on the real robot
        stages = tuple(x.strip() for x in settings.cue_stages.split(",") if x.strip())
        if features.sound_cues and voice and tts_mode == "piper" and settings.ack_tone == "star_trek_whistle":
            cue = SpeakerCue(stages=stages, peak=settings.ack_peak)
        elif settings.ack_tone != "off" and args.actuator == "serial" and features.sound_cues:
            cue = BuzzerCue(actuator, shift=settings.buzzer_shift, length=settings.buzzer_length,
                            stages=stages, volume=settings.buzzer_volume)
            cue.prime()
        else:
            cue = LogCue()

        tts = make_tts(tts_mode, piper_model_path=settings.piper_model_path, style=settings.voice_style)
        watcher = _start_battery_watch(args.actuator, actuator, tts=tts, audible=voice and tts_mode != "print")

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
            tts=tts,
            actuator=actuator,
            cue=cue,
            memory=memory,
            follow_up_s=settings.follow_up_s if voice else 0.0,
            question_window_s=settings.question_window_s if voice else 0.0,
        )
        try:
            loop.run_forever()
        finally:
            if watcher:
                watcher.stop()
            if memory:
                memory.close()


def make_battery_alert(tts, audible: bool, siren=None):
    """The low-battery alert: a diag event, then (when `audible`) the star_trek_red_alert siren twice, then G2 says so in its
    robot voice. `siren` is a callable that plays the siren and returns when it ends (default: the real one)."""
    from ..power.battery import ALERT_MESSAGES

    def on_alert(level, volts):
        diag.event("sys", "WARN", "battery.low", battery_level=level.name.lower(), volts=round(volts, 2))
        if not audible:
            return
        if siren is None:
            from . import star_trek_red_alert
            star_trek_red_alert.play(count=2, wait=True)
        else:
            siren()
        tts.speak(ALERT_MESSAGES[level])
    return on_alert


def _start_battery_watch(actuator_mode: str, actuator, *, tts, audible: bool):
    """Watch the robot's battery and play the star_trek_red_alert siren when it is low. Reads the voltage through the serial
    actuator, or, when the actuator is a mock (G2 is not allowed to move), through a read-only link of its own, since asking
    for the voltage moves nothing. No serial port (e.g. a laptop) means no watch."""
    import os

    from ..power.battery import BatteryMonitor, BatteryWatcher, read_voltage

    if not settings.battery_watch:
        return None
    if actuator_mode == "serial":
        reader = actuator.read_voltage
    elif os.path.exists(settings.serial_port):
        link_box: list = []

        def reader():
            if not link_box:
                from ..link.serial_link import SerialLink
                link_box.append(SerialLink(settings.serial_port, settings.serial_baud, reset_wait=0.5))
            return read_voltage(link_box[0])
    else:
        return None

    monitor = BatteryMonitor(settings.battery_low_v, settings.battery_critical_v)
    return BatteryWatcher(reader, make_battery_alert(tts, audible), monitor=monitor, poll_s=settings.battery_poll_s).start()


if __name__ == "__main__":
    main()
