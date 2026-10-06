"""A supervised exploration test: the behavior runtime on the real G2, with narration, and no voice loop.

    bash tools/g2_explore.sh start          # from the Mac: stops g2-voice, runs this, and ALWAYS restarts g2-voice when it ends
    bash tools/g2_explore.sh arm            # allow Tier 1 roam (Tier 0, the stationary "attentive" layer, is on from the start)
    bash tools/g2_explore.sh disarm         # end the roam bout
    bash tools/g2_explore.sh stop           # end the session

Control is a file (`~/.g2_explore_cmd`, one word: arm / disarm / halt / release / stop). Safety nets: the roam bout disarms by itself after
`--roam-s`, the whole session ends after `--max-s`, `kill -USR1 <pid>` or `halt` is the emergency stop, and G2's own fall guard is on.
There is NO edge detector: never run this on a desk, a table or the stand.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time

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


def main() -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.explore_session")
    ap.add_argument("--roam-s", type=float, default=60.0, help="a roam bout disarms itself after this long")
    ap.add_argument("--max-s", type=float, default=900.0, help="the whole session ends after this long")
    ap.add_argument("--no-narrate", action="store_true")
    ap.add_argument("--hz", type=float, default=8.0)
    args = ap.parse_args()

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
        memory = _make_memory()
        link = _make_link(True)
        if link is None:
            raise SystemExit("no serial link to the BiBoard")
        vision = _make_vision_source() if features.vision else None
        rt = _build_runtime(link, hz=args.hz, memory=None, frame_source=vision)     # no memory: place notes would name bonded people

        tts = None
        if not args.no_narrate:
            from .voice.tts import make_tts
            tts = make_tts("piper", piper_model_path=settings.piper_model_path, style=settings.voice_style)
            from .personality.bonds import Bonds
            attach(rt.bindings, Narrator(tts.speak, private=[b.label for b in Bonds.from_settings(settings)]))
            rt.bindings.tts = tts
            tts.speak("Exploration test starting. I will stay put and look around first.")

        from .gait.stand_guard import StandGuard
        guard = StandGuard(link, is_busy=lambda: rt.driver.mode.mode in (Mode.EXPLORE, Mode.APPROACH), guard=settings.stand_guard,
                           balance_off_idle=True, reenable_after_s=None).start()

        signal.signal(signal.SIGUSR1, lambda *_: rt.halt())
        signal.signal(signal.SIGUSR2, lambda *_: rt.release())
        signal.signal(signal.SIGTERM, lambda *_: rt.stop())
        t = threading.Thread(target=rt.run_forever, name="behavior", daemon=True)
        t.start()
        log.info("exploration session running (Tier 0 on). commands via %s: arm / disarm / halt / release / stop", CMD_FILE)

        started = time.monotonic()
        armed_at: float | None = None
        try:
            while t.is_alive() and time.monotonic() - started < args.max_s:
                time.sleep(0.5)
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
                if armed_at is not None and time.monotonic() - armed_at > args.roam_s:
                    rt.post(disarm_explore=True)
                    armed_at = None
                    log.warning("roam bout over (%.0f s): disarmed", args.roam_s)
        except KeyboardInterrupt:
            pass
        finally:
            log.info("ending the exploration session")
            try:
                rt.post(disarm_explore=True)
                time.sleep(1.0)
                link.send("d", read_reply=False, settle=0.0)                  # lie down, servos relaxed
                if tts is not None:
                    tts.speak("Exploration test finished.")
            except Exception:  # noqa: BLE001
                log.exception("clean-up failed")
            rt.stop()
            t.join(timeout=2.0)
            guard.stop()
            if vision is not None:
                vision.close()
            if memory is not None:
                memory.close()
            link.send("gp", read_reply=False, settle=0.0)
            link.close()


if __name__ == "__main__":
    main()
