"""`python -m pi_pipeline.app` -- the whole robot as one program.

The voice loop and the behaviour runtime run side by side over ONE shared serial
link: the voice loop handles wake -> listen -> Claude -> speak/act, and posts
`wake_word` / `conversation_ended` / `told_sleep` events to the runtime, which
otherwise drives idle / explore / sleep / gestures between conversations.

    python -m pi_pipeline.app                 # mock: no serial, dry-run power
    python -m pi_pipeline.app --serial        # talk to the BiBoard
    python -m pi_pipeline.app --no-voice      # just the behaviour runtime
    python -m pi_pipeline.app --no-behavior   # just the voice loop (== python -m pi_pipeline.voice)

Mock mode still runs the *real* sink + sensor code (against a null link), so this
is the integration surface: on hardware you add `--serial` and a camera feed,
nothing else changes.
"""
from __future__ import annotations

import argparse
import logging
import threading

from ..behavior import BehaviorDriver, BehaviorRuntime
from ..config import settings
from ..features import features, log_summary
from ..personality import Bonds, Personality
from .sensors import SensorHub
from .sinks import LockedLink, build_bindings

log = logging.getLogger("g2.app")


def _make_link(serial: bool):
    if not serial:
        return None
    from ..link.serial_link import SerialLink
    lk = SerialLink(settings.serial_port, settings.serial_baud)
    lk.connect()
    return LockedLink(lk)


def _build_runtime(link, *, hz: float):
    personality = Personality.from_settings(settings)
    bonds = Bonds.from_settings(settings)
    driver = BehaviorDriver(personality.behavior_params(),
                            vision_available=features.vision)
    bindings = build_bindings(link, dry_run_power=link is None)
    hub = SensorHub(link)
    rt = BehaviorRuntime(
        driver, bindings,
        sensors=hub.sample,
        roster=lambda: frozenset(b.label for b in bonds),
        hz=hz,
    )
    return rt


def _build_voice(on_event):
    from ..memory.memory import Memory
    from ..voice.actuator import make_actuator
    from ..voice.conversation import Conversation
    from ..voice.cues import LogCue
    from ..voice.loop import VoiceLoop
    from ..voice.stt import make_stt
    from ..voice.tts import make_tts
    from ..voice.wake_word import make_wake_word

    memory = None
    if settings.memory_enabled and features.memory:
        memory = Memory(settings)

    loop = VoiceLoop(
        wake_word=make_wake_word("none", vosk_model_path=settings.vosk_model_path,
                                 phrase=settings.wake_word),
        stt=make_stt("text", vosk_model_path=settings.vosk_model_path,
                     silence_s=settings.stt_silence_s),
        conversation=Conversation(settings),
        tts=make_tts("mac"),
        actuator=make_actuator("mock", port=settings.serial_port, baud=settings.serial_baud),
        cue=LogCue(),
        memory=memory,
        follow_up_s=0.0,
        on_event=on_event,
    )
    return loop, memory


def main() -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.app")
    ap.add_argument("--serial", action="store_true", help="talk to the BiBoard (default: mock)")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--no-behavior", action="store_true")
    ap.add_argument("--hz", type=float, default=8.0, help="behaviour tick rate")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S",
    )
    log_summary()
    lvl, msg = settings.api_key_expiry_status()
    if msg:
        (log.error if lvl == "expired" else log.warning)(msg)

    link = _make_link(args.serial)
    rt = None if args.no_behavior else _build_runtime(link, hz=args.hz)
    on_event = rt.post if rt is not None else None
    voice, memory = (None, None) if args.no_voice else _build_voice(on_event)

    if rt is None and voice is None:
        ap.error("nothing to run (--no-voice and --no-behavior)")

    rt_thread = None
    if rt is not None:
        rt_thread = threading.Thread(target=rt.run_forever, name="behavior", daemon=True)
        rt_thread.start()
        log.info("behaviour runtime started (%.0f Hz, %s)", args.hz,
                 "serial" if link else "mock")

    try:
        if voice is not None:
            voice.run_forever()                 # blocks until Ctrl-C / quit
        elif rt_thread is not None:
            rt_thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        if rt is not None:
            rt.stop()
        if rt_thread is not None:
            rt_thread.join(timeout=2.0)
        if memory is not None:
            memory.close()
        if link is not None:
            link.close()
        log.info("stopped")


if __name__ == "__main__":
    main()
