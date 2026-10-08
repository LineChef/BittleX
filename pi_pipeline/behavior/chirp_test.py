"""Listen to every behaviour chirp on the real BiBoard, through the same path the behaviour layer uses (CHIRP effect -> DriverBindings -> SerialActuatorSink -> SerialLink).

    python -m pi_pipeline.behavior.chirp_test [--gap 2.0] [--low N] [--only MOOD] [--also-low]

Run it with the voice service stopped (it owns the serial port): `sudo systemctl stop g2-voice` ... `sudo systemctl start g2-voice`. Each mood is announced on the console, played once and logged
(`g2.chirp` / `g2.noise`, and ~/.local/share/g2/noise.jsonl). `--low N` plays every note N semitones lower (the buzzer is loudest at the low end); `--also-low` plays each mood twice, as written and 10
semitones lower, so the two can be compared by ear. Nothing here moves a servo.
"""
from __future__ import annotations

import argparse
import logging
import time

from ..link import opencat
from .bindings import DriverBindings
from .chirps import CHIRP, ChirpMood
from .driver import Effect, EffectKind


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=float, default=2.0, help="seconds between chirps")
    ap.add_argument("--low", type=int, default=0, help="play every note this many semitones lower")
    ap.add_argument("--only", default=None, help="one mood by name")
    ap.add_argument("--also-low", action="store_true", help="play each mood again 10 semitones lower")
    ap.add_argument("--port", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from ..app.sinks import SerialActuatorSink
    from ..config import settings
    from ..link.serial_link import SerialLink
    link = SerialLink(a.port or settings.serial_port, settings.serial_baud)
    if not link.connect():
        print("could not open the BiBoard's serial port: is the voice service stopped?")
        return 1
    bind = DriverBindings(actuator=SerialActuatorSink(link))
    moods = [m for m in ChirpMood if a.only is None or m.value == a.only]
    plays = [(m, a.low) for m in moods]
    if a.also_low:
        plays = [p for m in moods for p in ((m, 0), (m, 10))]
    for mood, drop in plays:
        orig = CHIRP[mood]
        if drop:
            CHIRP[mood] = [(max(1, n - drop), d) for n, d in orig]
        try:
            print(f"playing {mood.value}{' (' + str(drop) + ' semitones lower)' if drop else ''}: {opencat.beep(CHIRP[mood])}", flush=True)
            bind.dispatch([Effect(EffectKind.CHIRP, mood, "chirp_test")])
        finally:
            CHIRP[mood] = orig
        time.sleep(a.gap)
    link.close()
    print("done: the noises are in ~/.local/share/g2/noise.jsonl (python -m pi_pipeline.link.noise_log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
