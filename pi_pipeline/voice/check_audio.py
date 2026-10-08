"""Audio diagnostics for the voice pipeline. No API key needed.

    python -m pi_pipeline.voice.check_audio devices        # list input/output devices
    python -m pi_pipeline.voice.check_audio wake           # loop; print each time the wake word fires
    python -m pi_pipeline.voice.check_audio stt            # transcribe one spoken utterance
    python -m pi_pipeline.voice.check_audio mic [SECONDS]   # record the microphone, print its level each second, then transcribe it (stop g2-voice first)
    python -m pi_pipeline.voice.check_audio tts "hello"    # speak text with the current Piper voice
    python -m pi_pipeline.voice.check_audio tts "hi" --model models/piper/en_US-amy-medium.onnx
"""
from __future__ import annotations

import argparse
import logging
import time

from ..config import settings


def _devices() -> None:
    import sounddevice as sd

    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] or d["max_output_channels"]:
            io = ("in" if d["max_input_channels"] else "") + ("out" if d["max_output_channels"] else "")
            print(f"  [{i}] {d['name']} ({io})")
    print("  default in/out:", sd.default.device)


def _wake() -> None:
    from .wake_word import VoskWakeWord

    ww = VoskWakeWord(settings.vosk_model_path, settings.wake_word)
    print(f'Listening for a wake phrase: "{settings.wake_word}"  (Ctrl+C to stop)')
    n = 0
    try:
        while True:
            ww.wait()
            n += 1
            print(f"  #{n}  heard it  ({time.strftime('%H:%M:%S')})")
    except KeyboardInterrupt:
        print(f"\n{n} trigger(s).")


def _stt() -> None:
    from .stt import VoskSTT

    stt = VoskSTT(settings.vosk_model_path, silence_s=settings.stt_silence_s)
    print("Speak now (stops after a pause)...")
    t0 = time.monotonic()
    text = stt.listen()
    print(f'  heard: {text!r}   ({time.monotonic() - t0:.1f}s)')


def _mic(seconds: float, wav_path: str) -> None:
    """Record the microphone with no wake word and no voice loop in the way: how loud is it, and what does the speech recogniser make of it?
    The recording is written to `wav_path` (a local file, never sent anywhere) so it can be played back."""
    import array
    import wave

    import sounddevice as sd

    from .stt import VoskSTT

    rate = 16000
    from . import wake_chime
    print("A chime means recording has started: say \"this is a dog bed\" right after it.")
    wake_chime.play(wait=True)
    print(f"Recording {seconds:.0f} s from the default microphone...")
    audio = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="int16")
    sd.wait()
    raw = audio.tobytes()
    samples = array.array("h", raw)
    for i in range(int(seconds)):
        chunk = samples[i * rate:(i + 1) * rate]
        peak = max(map(abs, chunk), default=0)
        mean = sum(chunk) / max(1, len(chunk))
        ac = (sum((x - mean) ** 2 for x in chunk) / max(1, len(chunk))) ** 0.5       # the level with the constant offset removed: speech lives here
        print(f"  second {i + 1}: peak {peak:5d}  dc offset {mean:7.1f}  speech-level (ac rms) {ac:7.1f}  " + "#" * min(60, int(ac // 40)))
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(raw)
    print(f"  saved {wav_path}")
    print(f"  recogniser heard: {VoskSTT.transcribe_wav(settings.vosk_model_path, wav_path)!r}")


def _tts(text: str, model: str | None, robot: bool | None) -> None:
    from .tts import PiperTTS

    style = settings.voice_style if robot is None else ("metal" if robot else "plain")
    PiperTTS(model or settings.piper_model_path, style=style).speak(text)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="pi_pipeline.voice.check_audio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    sub.add_parser("wake")
    sub.add_parser("stt")
    p_mic = sub.add_parser("mic")
    p_mic.add_argument("seconds", nargs="?", type=float, default=8.0)
    p_mic.add_argument("--wav", default="/tmp/g2_mic_test.wav")
    p_tts = sub.add_parser("tts")
    p_tts.add_argument("text")
    p_tts.add_argument("--model", default=None)
    p_tts.add_argument("--robot", dest="robot", action="store_true", default=None,
                       help="force the robot-voice effect on (default: settings.voice_robot_effect)")
    p_tts.add_argument("--no-robot", dest="robot", action="store_false",
                       help="force the robot-voice effect off")
    args = ap.parse_args()

    if args.cmd == "devices":
        _devices()
    elif args.cmd == "wake":
        _wake()
    elif args.cmd == "stt":
        _stt()
    elif args.cmd == "mic":
        _mic(args.seconds, args.wav)
    elif args.cmd == "tts":
        _tts(args.text, args.model, args.robot)


if __name__ == "__main__":
    main()
