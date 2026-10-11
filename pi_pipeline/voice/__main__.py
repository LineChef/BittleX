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
    from . import audio_gate as _gate
    _gate.install()                                   # one sound at a time: speech and sound effects wait for each other (voice/audio_gate.py)

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

        # crash forensics (diag/crashwatch.py): a heartbeat with the loop stage and resources, faulthandler to a file, and a report of the
        # previous process at the next start if it did not end cleanly (`python -m pi_pipeline.diag.crashwatch`)
        from ..diag.crashwatch import CrashWatch, StageTap
        stt_ref: dict = {}
        crash = CrashWatch("voice", extras=lambda: getattr(stt_ref.get("stt"), "last_info", None)).start()

        memory = None
        if settings.memory_enabled and not args.no_memory and features.memory:
            memory = Memory(settings)

        link = _open_shared_link(args.actuator)       # ONE locked serial link for the actuator, battery watch and stand guard
        fan = policy_walker = None
        if link is not None:
            from . import fail_sound
            link.on_failure = fail_sound.command_failed         # a motion command that cannot be sent plays the wrong-answer horn
        battery_alert = {"fn": None}                      # filled in once the speaker exists (below)
        if link is not None and args.actuator == "serial":
            from ..link.fanout import ImuFanout
            fan = ImuFanout(link)                          # the stand guard and the learned walk each get their own copy of the IMU stream
            if features.gait != "off" and settings.default_gait == "policy":
                from ..gait.policy_walker import PolicyWalker
                from . import prompt_tones
                policy_walker = PolicyWalker(fan.consumer(), on_battery=lambda lvl, v: battery_alert["fn"] and battery_alert["fn"](lvl, v),
                                             on_fall=lambda: prompt_tones.play_horn_if_enabled("G2_FALL_HORN"))     # the losing horn when he falls (user, 2026-10-10); it does not wait, the walker thread must rest him at once
        actuator = make_actuator(
            args.actuator, port=settings.serial_port, baud=settings.serial_baud, link=link,
            max_continuous_s=args.max_gait_s, balance_off_idle=settings.balance_off_idle, policy_walker=policy_walker,
        )
        guard = None
        if link is not None and (settings.stand_guard or settings.balance_off_idle):
            from ..gait.stand_guard import StandGuard
            guard = StandGuard(fan.consumer() if fan is not None else link, is_busy=lambda: getattr(actuator, "busy", False), guard=settings.stand_guard,
                               balance_off_idle=settings.balance_off_idle, reassert_s=settings.stand_reassert_s,
                               reenable_after_s=None if settings.balance_off_idle else 300.0,
                               on_fall=lambda: __import__("pi_pipeline.voice.prompt_tones", fromlist=["x"]).play_horn_if_enabled("G2_FALL_HORN")).start()   # tipped over at any time: the losing horn
            actuator.on_command = guard.note_activity
        # acknowledgement tone (the sound_cues feature flag turns all cues off): the whistle through the speaker when there
        # is one, else the buzzer cues on the real robot
        stages = tuple(x.strip() for x in settings.cue_stages.split(",") if x.strip())
        if features.sound_cues and voice and tts_mode == "piper" and settings.ack_tone in ("short_tone", "ack_whistle", "star_trek_whistle"):
            cue = SpeakerCue(stages=stages, peak=settings.ack_peak, tone=settings.ack_tone)
        elif settings.ack_tone != "off" and args.actuator == "serial" and features.sound_cues:
            cue = BuzzerCue(actuator, shift=settings.buzzer_shift, length=settings.buzzer_length,
                            stages=stages, volume=settings.buzzer_volume)
            cue.prime()
        else:
            cue = LogCue()
        cue = StageTap(cue, crash)

        if features.sound_cues and voice and tts_mode == "piper" and settings.api_tone == "on":
            from . import api_log, api_tone
            api_log.set_call_hook(lambda api, source: api_tone.play(settings.api_peak))     # a unique tone on every billed Claude call

        tts = make_tts(tts_mode, piper_model_path=settings.piper_model_path, style=settings.voice_style)
        audible = voice and tts_mode != "print"
        battery_alert["fn"] = make_battery_alert(tts, audible)     # also used for low readings taken while walking
        watcher = _start_battery_watch(args.actuator, actuator, tts=tts, audible=audible, link=link)
        if watcher is not None:
            actuator.on_before_gait = watcher.read_before          # a reading right before any walk starts (there is no idle timer)
        power_log = _start_power_log()
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
                wait_still = None
                if fan is not None:
                    from ..gait.stillness import StillnessWaiter
                    wait_still = StillnessWaiter(fan.consumer().poll_imu).wait      # no picture until the IMU shows G2 has stopped swaying (camera shake)
                camera = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0,
                                           ae_bump=settings.vision_ae_bump, on_capture=on_capture,
                                           save_dir=settings.vision_save_dir or None,
                                           keep_days=settings.picture_keep_days,
                                           exposure_check=settings.vision_exposure_check,
                                           meter_every_s=0.0, wait_still=wait_still)      # meter the light before EVERY picture (user, 2026-10-10: pictures are rare now)

        namer = None
        if camera is not None:                             # "this is the dishwasher" works in plain voice mode too, not only inside an exploration session
            import os
            from ..vision.exploration_pictures import DEFAULT_ROOT, ExplorationPictureSaver
            namer = ExplorationPictureSaver(camera, os.environ.get("G2_EXPLORE_PICTURES_DIR", DEFAULT_ROOT))

        watcher_c = None
        from ..memory.call_log import MemoryCallGate
        call_gate = MemoryCallGate(lambda: memory.recency()[0]) if memory else None      # at most ONE memory-processing Claude call per session, across the tidy-up and the reflection
        if memory and settings.consolidate and settings.anthropic_api_key:
            from ..memory.consolidate import Consolidator, ConsolidationWatcher, make_llm
            from .usage import UsageTracker
            watcher_c = ConsolidationWatcher(
                Consolidator(memory.store, make_llm(settings), usage=UsageTracker(settings.usage_path) if settings.usage_path else None,
                             audit_path="~/.local/share/g2/memory_consolidation.jsonl",
                             min_new_exchanges=settings.consolidate_min_exchanges),
                lambda: memory.recency()[0], idle_s=settings.consolidate_idle_s,
                min_interval_s=settings.consolidate_min_interval_s, gate=call_gate).start()

        watcher_r = None
        if memory and settings.consolidate and settings.anthropic_api_key and settings.reflect in ("dry", "on"):
            from ..memory.consolidate import ConsolidationWatcher, make_llm
            from ..reflection.reflect import ExperienceReflector
            from .usage import UsageTracker
            watcher_r = ConsolidationWatcher(
                ExperienceReflector(memory.store, make_llm(settings, "reflect"), mode=settings.reflect, usage=UsageTracker(settings.usage_path) if settings.usage_path else None),
                lambda: memory.recency()[0], idle_s=settings.consolidate_idle_s, min_interval_s=settings.consolidate_min_interval_s, gate=call_gate, kind="reflection").start()      # level 2: his own experience, one call per new session

        wake = make_wake_word(
            "vosk" if use_wake else "none",
            vosk_model_path=settings.vosk_model_path,
            phrase=settings.wake_word,
        )
        stt = make_stt(
            "vosk" if voice else "text",
            vosk_model_path=settings.vosk_model_path,
            silence_s=settings.stt_silence_s,
        )
        stt_ref["stt"] = stt
        if hasattr(wake, "hand_over") and hasattr(stt, "_Recognizer"):
            stt.audio_source = wake.hand_over      # one microphone stream from the wake word through the command
        def on_event(**kw):
            # no battery read at the wake word: each `P` makes the BiBoard tick, which sounded like the board answering the wake word and
            # landed inside the command window (2026-10-08). Readings are taken before each walk and on the slow backstop timer instead.
            if watcher_c and kw.get("told_sleep"):
                watcher_c.nudge()
            if watcher_r and kw.get("told_sleep"):
                watcher_r.nudge()
            if kw.get("arm_explore") and settings.explore_handover and args.actuator == "serial":
                # the voice service has no behavior runtime: hand over to an exploration session once the spoken reply is finished
                import threading
                from ..explore_launch import launch
                threading.Timer(5.0, lambda: launch(settings.explore_roam_s)).start()

        if voice and link is not None and settings.sleep_after_s > 0:           # power-saving sleep after a long rest (user, 2026-10-10)
            from ..power import power as _power
            from ..power.sleep_watch import SleepWatch, WakeHook
            from . import prompt_tones
            _sleep_steps = [lambda: prompt_tones.play_sigh(wait=True), lambda: _power.set_wifi_power_save(True)]
            _wake_steps = [lambda: prompt_tones.play_yawn(wait=True), lambda: _power.set_wifi_power_save(False)]
            if guard is not None:
                _sleep_steps.append(guard.pause)
                _wake_steps.append(guard.resume)
            sleep_watch = SleepWatch(is_resting=lambda: getattr(link, "last_motion_command", "") in ("", "d"),
                                     is_busy=lambda: getattr(actuator, "busy", False), after_s=settings.sleep_after_s,
                                     on_sleep=_sleep_steps, on_wake=_wake_steps,
                                     on_event=(power_log.event if power_log else None)).start()
            _prev_on_command = getattr(actuator, "on_command", None)

            def _on_command(_prev=_prev_on_command):
                sleep_watch.note_activity("command")
                if _prev is not None:
                    _prev()
            actuator.on_command = _on_command
            wake = WakeHook(wake, sleep_watch)
        loop = VoiceLoop(
            wake_word=wake,
            stt=stt,
            conversation=Conversation(settings),
            tts=tts,
            actuator=actuator,
            cue=cue,
            memory=memory,
            follow_up_s=settings.follow_up_s if voice else 0.0,
            question_window_s=settings.question_window_s if voice else 0.0,
            conversation_window_s=settings.conversation_window_s if voice else 0.0,
            conversation_max_s=settings.conversation_max_s,
            side_max_words=settings.side_max_words if voice else 0,
            conversation_max_words=settings.conversation_max_words if voice else 0,
            camera=camera,
            namer=namer,
            announce_online=os.environ.get("G2_ANNOUNCE_ONLINE", "on").strip().lower() not in ("off", "0", "false", "no"),
            on_event=on_event,
            on_power=(stop_pi_watch.set_on_battery if stop_pi_watch else None),
            on_poweroff=((lambda: power_off_pi(actuator)) if (voice and settings.poweroff_on_shutdown) else None),
            shutdown_confirm_s=settings.shutdown_confirm_s,
        )
        try:
            loop.run_forever()
        finally:
            crash.stop()                                  # a normal end (Ctrl-C, systemctl stop) is not reported as a crash at the next start
            if watcher:
                watcher.stop()
            if guard:
                guard.stop()
            if camera:
                camera.close()
            if watcher_c:
                watcher_c.stop()
            if watcher_r:
                watcher_r.stop()
            if link is not None:
                link.close()
            if stop_pi_watch:
                stop_pi_watch.stop()
            if power_log:
                power_log.stop()
            if memory:
                memory.close()


def _play_whistle() -> None:
    from . import ack_whistle
    ack_whistle.play(peak=settings.alert_peak, wait=True)


def _play_siren() -> None:
    from . import red_alert_siren
    red_alert_siren.play(peak=settings.alert_peak, count=2, wait=True)


def _sound_then_say(tts, text: str, sound) -> None:
    """Play an alert sound (a blocking callable), then say `text` in G2's robot voice."""
    sound()
    tts.speak(text)


def make_battery_alert(tts, audible: bool, sound=None):
    """G2's own pack (read as a voltage) is low: a diag event, then (when `audible`) the ack_whistle and a spoken line.
    `sound` replaces the whistle in tests."""
    from ..power.battery import ALERT_MESSAGES

    def on_alert(level, volts):
        diag.event("sys", "WARN", "battery.low", battery_level=level.name.lower(), volts=round(volts, 2))
        if audible:
            _sound_then_say(tts, ALERT_MESSAGES[level], sound or _play_whistle)
    return on_alert


def make_pi_battery_alert(tts, audible: bool, sound=None):
    """The Pi's battery is probably about 80% used (estimated from uptime): the red_alert_siren siren twice, then a line saying
    which battery. `sound` replaces the siren in tests."""
    from ..power.battery import PI_ALERT_MESSAGES

    def on_alert(level, used_fraction):
        diag.event("sys", "WARN", "pi_battery.low", battery_level=level.name.lower(), used=round(used_fraction, 2))
        if audible:
            _sound_then_say(tts, PI_ALERT_MESSAGES[level], sound or _play_siren)
    return on_alert


def _start_power_log():
    """The always-on power diary (power/power_log.py; Linux/Pi only): settles the previous boot (a power loss becomes a measured Pi runtime),
    then logs start, sleep / wake and a heartbeat every minute. Returns the PowerLog or None."""
    import sys

    if sys.platform != "linux":
        return None
    from ..power.power_log import PowerLog
    from ..power.runtime_tracker import RuntimeTracker

    try:
        plog = PowerLog()
        tracker = RuntimeTracker(settings.pi_runtime_log)
        plog.collect_into(tracker, record=tracker.collect() is None)   # an intentional battery test records its own run; don't count it twice
        return plog.start()
    except Exception:  # noqa: BLE001 -- diagnostics must never stop the voice service
        import logging
        logging.getLogger("g2.powerlog").warning("power log not started", exc_info=True)
        return None


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
    watcher = RuntimeWatcher(tracker, make_pi_battery_alert(tts, audible), full_runtime_s=settings.pi_full_runtime_s or None, warn_fraction=settings.pi_warn_fraction, critical_fraction=settings.pi_critical_fraction,
                             require_arm=settings.pi_battery_arm == "manual").start()
    import types
    return types.SimpleNamespace(stop=watcher.stop, set_on_battery=lambda on: tracker.arm_now() if on else tracker.disarm())


def power_off_pi(actuator, *, run=None, platform=None, sleep=None) -> None:
    """Lie G2 down, then shut the Pi down cleanly (`sudo -n shutdown -h now`; systemd stops this service on the way, so the memory database
    and logs are closed properly). On anything but Linux (a laptop) it only logs. Raises if the shutdown command fails."""
    import subprocess
    import sys
    import time

    platform = platform or sys.platform
    run = run or subprocess.run
    sleep = sleep or time.sleep
    try:
        actuator.stop()                                    # `d`: rest posture, servos off (a no-op for the mock actuator)
    except Exception:  # noqa: BLE001
        pass
    sleep(3.0)                                             # let him settle
    if platform != "linux":
        logging.getLogger("g2.voice").warning("power-off requested, but this is not a Pi (%s): not shutting anything down", platform)
        return
    run(["sudo", "-n", "shutdown", "-h", "now"], check=True, timeout=20)


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
    """Watch the robot's battery and play the red_alert_siren siren when it is low. Reads the voltage through the serial
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
    from ..power.battery import make_voltage_log
    return BatteryWatcher(reader, make_battery_alert(tts, audible), monitor=monitor, poll_s=settings.battery_poll_s,
                          record=make_voltage_log(settings.battery_log), record_every_s=settings.battery_log_every_s).start()


if __name__ == "__main__":
    main()
