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
    if settings.clear_captures:
        from ..util.tidy import clear_folder
        clear_folder(settings.capture_dir, min_age_s=settings.capture_keep_s)
    if settings.vision_save_dir:
        from ..vision.pictures import prune_old
        prune_old(settings.vision_save_dir, settings.picture_keep_days)
    if settings.tidy_days > 0:
        from ..diag.core import _log_root
        from ..util.tidy import tidy_startup
        tidy_startup([_log_root(), settings.runs_dir], settings.tidy_days)

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

        link = _open_shared_link(args.actuator)       # ONE locked serial link for the actuator, battery watch and stand guard
        actuator = make_actuator(
            args.actuator, port=settings.serial_port, baud=settings.serial_baud, link=link,
            max_continuous_s=args.max_gait_s, balance_off_idle=settings.balance_off_idle,
        )
        guard = None
        if link is not None and (settings.stand_guard or settings.balance_off_idle):
            from ..gait.stand_guard import StandGuard
            guard = StandGuard(link, is_busy=lambda: getattr(actuator, "busy", False), guard=settings.stand_guard,
                               balance_off_idle=settings.balance_off_idle,
                               reenable_after_s=None if settings.balance_off_idle else 300.0).start()
            actuator.on_command = guard.note_activity
        # acknowledgement tone (the sound_cues feature flag turns all cues off): the whistle through the speaker when there
        # is one, else the buzzer cues on the real robot
        stages = tuple(x.strip() for x in settings.cue_stages.split(",") if x.strip())
        if features.sound_cues and voice and tts_mode == "piper" and settings.ack_tone in ("short_tone", "star_trek_whistle"):
            cue = SpeakerCue(stages=stages, peak=settings.ack_peak, tone=settings.ack_tone)
        elif settings.ack_tone != "off" and args.actuator == "serial" and features.sound_cues:
            cue = BuzzerCue(actuator, shift=settings.buzzer_shift, length=settings.buzzer_length,
                            stages=stages, volume=settings.buzzer_volume)
            cue.prime()
        else:
            cue = LogCue()

        tts = make_tts(tts_mode, piper_model_path=settings.piper_model_path, style=settings.voice_style)
        audible = voice and tts_mode != "print"
        watcher = _start_battery_watch(args.actuator, actuator, tts=tts, audible=audible, link=link)
        stop_pi_watch = _start_pi_battery_watch(tts=tts, audible=audible)

        camera = None
        if voice and features.vision and settings.vision_describe:
            import os
            if os.path.exists(settings.vision_serial_port):
                from ..vision.snapshot import CameraSnapshotter
                # 240x240: the module truncates the 480x480 jpeg; ae_bump brightens a dim room as the detection feed does
                on_capture = None
                if settings.camera_sounds and tts_mode != "print":
                    from . import camera_sounds
                    on_capture = lambda: camera_sounds.play("shutter", settings.camera_peak)  # noqa: E731
                camera = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0,
                                           ae_bump=settings.vision_ae_bump, on_capture=on_capture,
                                           save_dir=settings.vision_save_dir or None,
                                           keep_days=settings.picture_keep_days,
                                           exposure_check=settings.vision_exposure_check)

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
            camera=camera,
        )
        try:
            loop.run_forever()
        finally:
            if watcher:
                watcher.stop()
            if guard:
                guard.stop()
            if camera:
                camera.close()
            if link is not None:
                link.close()
            if stop_pi_watch:
                stop_pi_watch()
            if memory:
                memory.close()


def _play_whistle() -> None:
    from . import star_trek_whistle
    star_trek_whistle.play(peak=settings.alert_peak, wait=True)


def _play_siren() -> None:
    from . import star_trek_red_alert
    star_trek_red_alert.play(peak=settings.alert_peak, count=2, wait=True)


def _sound_then_say(tts, text: str, sound) -> None:
    """Play an alert sound (a blocking callable), then say `text` in G2's robot voice."""
    sound()
    tts.speak(text)


def make_battery_alert(tts, audible: bool, sound=None):
    """G2's own pack (read as a voltage) is low: a diag event, then (when `audible`) the star_trek_whistle and a spoken line.
    `sound` replaces the whistle in tests."""
    from ..power.battery import ALERT_MESSAGES

    def on_alert(level, volts):
        diag.event("sys", "WARN", "battery.low", battery_level=level.name.lower(), volts=round(volts, 2))
        if audible:
            _sound_then_say(tts, ALERT_MESSAGES[level], sound or _play_whistle)
    return on_alert


def make_pi_battery_alert(tts, audible: bool, sound=None):
    """The Pi's battery is probably about 80% used (estimated from uptime): the star_trek_red_alert siren twice, then a line saying
    which battery. `sound` replaces the siren in tests."""
    from ..power.battery import PI_ALERT_MESSAGES

    def on_alert(level, used_fraction):
        diag.event("sys", "WARN", "pi_battery.low", battery_level=level.name.lower(), used=round(used_fraction, 2))
        if audible:
            _sound_then_say(tts, PI_ALERT_MESSAGES[level], sound or _play_siren)
    return on_alert


def _start_pi_battery_watch(*, tts, audible: bool):
    """Startup hook for the Pi-battery work (Linux/Pi only). Settles a battery test left from the previous boot, if one was started
    on purpose (nothing happens when there is none), and, only if G2_PI_BATTERY_WATCH=1, starts the 80%-of-runtime warning.
    Returns a stopper or None."""
    import sys

    if sys.platform != "linux":
        return None
    from ..power.runtime_tracker import RuntimeTracker, RuntimeWatcher

    tracker = RuntimeTracker(settings.pi_runtime_log)
    tracker.collect()
    if not settings.pi_battery_watch:
        return None
    watcher = RuntimeWatcher(tracker, make_pi_battery_alert(tts, audible),
                             full_runtime_s=settings.pi_full_runtime_s or None).start()
    return watcher.stop


def _open_shared_link(actuator_mode: str):
    """The one serial link the voice service shares (actuator, battery watch, stand guard), locked for threads; None if there is no
    serial port to open (e.g. a laptop) or nothing needs it."""
    import os

    needed = actuator_mode == "serial" or settings.battery_watch or settings.stand_guard or settings.balance_off_idle
    if not needed or not os.path.exists(settings.serial_port):
        return None
    from ..link.locked import LockedLink
    from ..link.serial_link import SerialLink

    lk = SerialLink(settings.serial_port, settings.serial_baud, reset_wait=0.5)
    return LockedLink(lk) if lk.connect() else None


def _start_battery_watch(actuator_mode: str, actuator, *, tts, audible: bool, link=None):
    """Watch the robot's battery and play the star_trek_red_alert siren when it is low. Reads the voltage through the serial
    actuator, or, when the actuator is a mock (G2 is not allowed to move), through a read-only link of its own, since asking
    for the voltage moves nothing. No serial port (e.g. a laptop) means no watch."""
    import os

    from ..power.battery import BatteryMonitor, BatteryWatcher, read_voltage

    if not settings.battery_watch:
        return None
    if actuator_mode == "serial":
        reader = actuator.read_voltage
    elif link is not None:
        def reader():
            return read_voltage(link)
    else:
        return None

    monitor = BatteryMonitor(settings.battery_low_v, settings.battery_critical_v)
    return BatteryWatcher(reader, make_battery_alert(tts, audible), monitor=monitor, poll_s=settings.battery_poll_s).start()


if __name__ == "__main__":
    main()
