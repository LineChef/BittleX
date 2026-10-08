"""A supervised exploration test: the behavior runtime on the real G2, with narration, and no voice loop.

    bash tools/g2_explore.sh start          # from the Mac: stops g2-voice, runs this, and ALWAYS restarts g2-voice when it ends; G2 starts ROAMING at once (Tier 1)
    bash tools/g2_explore.sh stationary     # opt-in: stay put (Tier 0, the stationary "attentive" layer) until `arm`
    bash tools/g2_explore.sh arm            # allow Tier 1 roam
    bash tools/g2_explore.sh disarm         # end the roam bout
    bash tools/g2_explore.sh stop           # end the session

Control is a file (`~/.g2_explore_cmd`, one word: arm / disarm / halt / release / stop). Roaming has no time cap (`--roam-s N` adds one); the whole session
ends after `--max-s` (2 h). Voice works after the wake word: "emergency stop", "resume", "go ahead and look around", "that's enough",
"tell me what you see" (what the detector sees, no API call), "shut down" (ends the session only). `kill -USR1 <pid>` or `halt` is the
emergency stop, and G2's own fall guard is on.
There is NO edge detector: never run this on a desk, a table or the stand.
"""
from __future__ import annotations

import argparse
import logging
import os
import queue
import signal
import threading
import time
import types

log = logging.getLogger("g2.explore_session")
CMD_FILE = os.path.expanduser("~/.g2_explore_cmd")


def _read_command() -> str:
    try:
        with open(CMD_FILE) as f:
            word = f.read().strip().lower()
        os.remove(CMD_FILE)
        return word
    except OSError:
        return ""


def apply_roam_limits(driver, roam_s: float) -> None:
    """Make the session's `--roam-s` the only limit on a roam bout. The behavior layer has two caps of its own that would end a bout early and drop G2 into the attentive idle
    (a periodic look-around, then sit and rest, which looks like being stuck): the explorer's leg budget (8 legs) and the mode controller's 90 s cap on one armed bout.
    The session ends the bout itself at `roam_s` (0 = no cap), so the controller's cap is set just above it."""
    from dataclasses import replace
    driver.explorer.cfg = replace(driver.explorer.cfg, max_legs=10 ** 9)
    driver.mode.cfg = replace(driver.mode.cfg, explore_max_secs=(roam_s + 5.0) if roam_s > 0 else 1e9)


def parse_args(argv=None):
    """Roaming (Tier 1) starts at once by default; `--stationary` is the opt-in stay-put mode (Tier 0 only, until `arm`)."""
    ap = argparse.ArgumentParser(prog="pi_pipeline.explore_session")
    ap.add_argument("--roam-s", type=float, default=600.0, help="a roam bout disarms itself after this long (0 = no cap)")
    ap.add_argument("--stationary", action="store_true", help="opt-in: stay put (Tier 0, the stationary attentive layer) until `arm`; the default is to start roaming at once")
    ap.add_argument("--arm-on-start", action="store_true", help="start roaming at once (now the default; kept for the voice hand-over)")
    ap.add_argument("--exit-when-roam-ends", action="store_true", help="end the session (the voice service comes back) when roaming ends")
    ap.add_argument("--max-s", type=float, default=7200.0, help="the whole session ends after this long, so a forgotten session cannot keep the voice service off")
    ap.add_argument("--no-narrate", action="store_true")
    ap.add_argument("--hz", type=float, default=8.0)
    args = ap.parse_args(argv)
    args.arm_on_start = args.arm_on_start or not args.stationary
    return args


def main() -> None:
    args = parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    from .app.__main__ import _build_runtime, _make_link, _make_memory, _make_vision_source
    from .behavior.mode_controller import Mode
    from .behavior.narrator import Narrator, attach
    from .config import settings
    from .diag import diag
    from .features import features

    if not features.explore:
        raise SystemExit("exploration is off in G2_FEATURES (+explore, +vision, +vision_safety are needed); nothing to test")

    with diag.session("explore", extra={"roam_s": args.roam_s}):
        from .diag.crashwatch import CrashWatch
        crash = CrashWatch("explore", extras=lambda: getattr(stt_holder.get("stt"), "last_info", None)).start()
        stt_holder: dict = {}
        memory = _make_memory()
        link = _make_link(True)
        if link is None:
            raise SystemExit("no serial link to the BiBoard")
        vision = _make_vision_source() if features.vision else None
        # place notes ("the dog is often to the left") come from the behavior thread, but the memory database belongs to this one:
        # queue them and write them from the main loop below
        notes: "queue.Queue[str]" = queue.Queue()
        deferred = types.SimpleNamespace(store=types.SimpleNamespace(add_fact=notes.put)) if memory is not None else None
        from .link.fanout import ImuFanout
        fan = ImuFanout(link)                              # the sensor hub, the stand guard and the learned walk each get their own IMU stream
        alert = {"fn": None}                              # the battery alarm, set once the speaker exists
        policy_walker = None
        fall = {"fn": None}                               # set once the runtime and the voice exist: a fall halts the exploration
        if features.gait != "off" and settings.default_gait == "policy":
            from .gait.policy_walker import PolicyWalker
            policy_walker = PolicyWalker(fan.consumer(), on_battery=lambda lvl, v: alert["fn"] and alert["fn"](lvl, v),
                                         on_fall=lambda: fall["fn"] and fall["fn"]())
        saver = None
        if vision is not None and os.environ.get("G2_EXPLORE_SURVEY", "1") != "0":
            from .vision.exploration_pictures import DEFAULT_ROOT, ExplorationPictureSaver
            saver = ExplorationPictureSaver(vision, os.environ.get("G2_EXPLORE_PICTURES_DIR", DEFAULT_ROOT))
        rt = _build_runtime(link, hz=args.hz, memory=deferred, frame_source=vision, policy_walker=policy_walker, imu_link=fan.consumer(),
                            camera_snapshot=saver)
        if saver is not None:
            rt.driver.enable_survey()                  # stop at the end of each leg, look down and up, one picture each (behavior/survey.py)
            log.info("survey stops ON: pictures go to %s", saver._root)

        apply_roam_limits(rt.driver, args.roam_s)          # roaming lasts as long as --roam-s says, not the behavior layer's own short caps

        tts = None
        narrator = None
        say = lambda text: None  # noqa: E731
        if not args.no_narrate:
            from .voice.tts import make_tts
            raw = make_tts("piper", piper_model_path=settings.piper_model_path, style=settings.voice_style)
            lock = threading.Lock()

            class _Locked:                                                    # narration and replies never talk over each other
                def speak(self, text):
                    with lock:
                        raw.speak(text)

            tts = _Locked()
            say = tts.speak
            from .voice.__main__ import make_battery_alert
            alert["fn"] = make_battery_alert(tts, True)
            from .personality.bonds import Bonds
            hide = os.environ.get("G2_NARRATE_HIDE_NAMES") == "1"          # off by default: G2 may say the names he knows
            narrator = Narrator(tts.speak, private=[b.label for b in Bonds.from_settings(settings)] if hide else ())
            attach(rt.bindings, narrator)
            rt.bindings.tts = tts
            say("Exploration test starting. I will stay put and look around first." if args.stationary else "Exploration test starting.")

        def _on_fall():
            log.warning("G2 fell: halting the exploration so he does not keep trying to walk (release with `g2_explore.sh release`, or end the session)")
            rt.halt()
            try:
                link.send("gb", read_reply=False, settle=0.0)         # balance off: lying (or held) upside down, the gyro balance loop fights the servos and G2 twitches
            except Exception:  # noqa: BLE001
                log.debug("could not switch balance off after the fall", exc_info=True)
            threading.Thread(target=say, args=("I fell down. I have stopped.",), daemon=True).start()   # this runs on the walker thread: never wait for the speaker here
        fall["fn"] = _on_fall

        from .gait.stand_guard import StandGuard
        guard = StandGuard(fan.consumer(), is_busy=lambda: rt.driver.mode.mode in (Mode.EXPLORE, Mode.APPROACH) or (policy_walker is not None and policy_walker.busy), guard=settings.stand_guard,
                           balance_off_idle=True, reassert_s=settings.stand_reassert_s, reenable_after_s=None).start()

        # this session has stopped the voice service, so it must watch G2's battery itself (reads pause while a walk is running;
        # the walk loop checks the voltage under load)
        from .power.battery import BatteryMonitor, BatteryWatcher, make_voltage_log, read_voltage
        watcher = BatteryWatcher(lambda: None if (policy_walker is not None and policy_walker.busy) else read_voltage(link),
                                 lambda lvl, v: alert["fn"] and alert["fn"](lvl, v),
                                 monitor=BatteryMonitor(settings.battery_low_v, settings.battery_critical_v), poll_s=settings.battery_poll_s,
                                 record=make_voltage_log(settings.battery_log), record_every_s=settings.battery_log_every_s).start()
        stop_flag = threading.Event()
        listener = None

        def _wake_chime():
            if features.sound_cues and not args.no_narrate:
                from .voice import wake_chime
                wake_chime.play(settings.ack_peak)
        if features.mic and features.wake_word:
            from .behavior.explore_listener import ExploreListener
            from .voice.stt import make_stt
            from .voice.wake_word import make_wake_word
            wake = make_wake_word("vosk", vosk_model_path=settings.vosk_model_path, phrase=settings.wake_word)
            stt = make_stt("vosk", vosk_model_path=settings.vosk_model_path, silence_s=settings.stt_silence_s)
            stt_holder["stt"] = stt
            if hasattr(wake, "hand_over"):
                stt.audio_source = wake.hand_over
            listener = ExploreListener(wake, stt, say, rt, lambda: rt._frame_source(),
                                       on_arm=lambda: link.send("gB", read_reply=False, settle=0.0),
                                       on_stop=stop_flag.set, chime=_wake_chime,
                                       quiet=narrator.quiet if narrator is not None else None).start()
            log.info("voice commands on: wake word, then arm/disarm roam, stop, resume, \"tell me what you see\", shut down (ends the session)")

        signal.signal(signal.SIGUSR1, lambda *_: rt.halt())
        signal.signal(signal.SIGUSR2, lambda *_: rt.release())
        signal.signal(signal.SIGTERM, lambda *_: rt.stop())
        t = threading.Thread(target=rt.run_forever, name="behavior", daemon=True)
        t.start()
        try:
            os.remove(CMD_FILE)                              # a command left behind by an earlier session must not act on this one
        except OSError:
            pass
        log.info("exploration session running (Tier 0 on). commands via %s: arm / disarm / halt / release / stop", CMD_FILE)

        started = time.monotonic()
        armed_at: float | None = None
        was_exploring, left_at = False, None
        if args.arm_on_start:
            link.send("gB", read_reply=False, settle=0.0)
            rt.post(arm_explore=True)
            armed_at = started
            say("Okay, exploring.")
        try:
            while t.is_alive() and not stop_flag.is_set() and time.monotonic() - started < args.max_s:
                time.sleep(0.5)
                while memory is not None and not notes.empty():
                    try:
                        memory.store.add_fact(notes.get_nowait())
                    except Exception:  # noqa: BLE001
                        log.exception("saving a place note failed")
                cmd = _read_command()
                if cmd == "stop":
                    break
                if cmd == "arm":
                    link.send("gB", read_reply=False, settle=0.0)              # balance on for walking
                    rt.post(arm_explore=True)
                    armed_at = time.monotonic()
                    log.warning("roam ARMED for up to %.0f s", args.roam_s)
                elif cmd == "disarm":
                    rt.post(disarm_explore=True)
                    armed_at = None
                    log.warning("roam disarmed")
                elif cmd == "halt":
                    rt.halt()
                elif cmd == "release":
                    rt.release()
                if args.roam_s > 0 and armed_at is not None and time.monotonic() - armed_at > args.roam_s:
                    rt.post(disarm_explore=True)
                    armed_at = None
                    log.warning("roam bout over (%.0f s): disarmed", args.roam_s)
                    if args.exit_when_roam_ends:
                        break
                if args.exit_when_roam_ends:                       # roaming ended some other way ("that's enough", picked up, ...)
                    mode = rt.driver.mode.mode
                    if mode in (Mode.EXPLORE, Mode.APPROACH):
                        was_exploring, left_at = True, None
                    elif was_exploring:
                        left_at = left_at or time.monotonic()
                        if time.monotonic() - left_at > 4.0:
                            log.info("roaming ended: leaving the exploration session")
                            break
                    elif armed_at is not None and time.monotonic() - armed_at > 90.0:
                        log.warning("roaming never started: leaving the exploration session")
                        break
                    elif armed_at is None and not was_exploring:
                        break
        except KeyboardInterrupt:
            pass
        finally:
            crash.stop()
            if listener is not None:
                listener.stop()
            log.info("ending the exploration session")
            try:
                rt.post(disarm_explore=True)
                time.sleep(1.0)
                say("Exploration completed.")                                 # said first (user, 2026-10-07), then G2 lies down
                link.send("d", read_reply=False, settle=0.0)                  # lie down, servos relaxed
            except Exception:  # noqa: BLE001
                log.exception("clean-up failed")
            if policy_walker is not None:
                policy_walker.stop(rest=True)
            rt.stop()
            t.join(timeout=2.0)
            guard.stop()
            watcher.stop()
            if vision is not None:
                vision.close()
            if memory is not None:
                memory.close()
            link.send("gp", read_reply=False, settle=0.0)
            link.close()


if __name__ == "__main__":
    main()
