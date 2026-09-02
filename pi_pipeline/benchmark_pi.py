"""Benchmark the voice pipeline on the real Pi (or anywhere).

One shot, headless, run over SSH once pi_pipeline is installed:

    python -m pi_pipeline.benchmark_pi                 # everything it can
    python -m pi_pipeline.benchmark_pi --skip-api      # no Claude round-trips
    python -m pi_pipeline.benchmark_pi --skip-stress   # no CPU-load / thermal test

Every section is independent and degrades gracefully: a missing model, missing
API key, or non-Linux host just prints SKIP and the run continues. Nothing here
needs the robot.

Measures the things docs/research/pi-bring-up.md flags as untested on a Zero 2 W:
  - RAM headroom idle -> voice stack loaded -> mid-exchange
  - Piper synth time as x realtime  (want < 1.0)
  - Vosk transcription time as x realtime
  - Claude API round-trip latency (p50/p95)
  - CPU-load thermal rise + throttling + scheduler responsiveness (did the
    Wi-Fi power-save / swap setup hold up)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import wave
from pathlib import Path

from .config import settings

LINUX = platform.system() == "Linux"
SENTENCE = ("The quick brown fox jumps over the lazy dog while G2 walks a "
            "slow careful circle around the kitchen table.")

# ------------------------------------------------------------------ helpers ---
class Row:
    def __init__(self, rows): self.rows = rows
    def add(self, section, metric, value, verdict=""):
        self.rows.append((section, metric, value, verdict))

def _rss_kb() -> int | None:
    """This process's resident set, KB. Linux-only (reads /proc/self/status)."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    try:
        import resource
        m = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return m // 1024 if platform.system() == "Darwin" else m  # macOS: bytes
    except Exception:
        return None

def _mem_available_kb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    except OSError:
        return None

def _mb(kb): return "n/a" if kb is None else f"{kb / 1024:.0f} MB"

def _sh(*cmd) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return None

# ------------------------------------------------------------------ sections --
def sec_system(out: Row) -> None:
    print("\n=== system ===")
    model = None
    for p in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            model = Path(p).read_text().strip("\x00").strip(); break
        except OSError:
            pass
    cores = os.cpu_count()
    total_kb = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                total_kb = int(line.split()[1])
    except OSError:
        pass
    py = platform.python_version()
    kern = platform.release()
    for k, v in (("model", model or platform.platform()),
                 ("cores", cores), ("RAM total", _mb(total_kb)),
                 ("python", py), ("kernel", kern)):
        print(f"  {k:<12} {v}")
        out.add("system", k, v)
    if not LINUX:
        print("  (not Linux — RAM / thermal sections will SKIP)")

def sec_ram_and_voice(out: Row, sentence: str) -> tuple[Path | None, object | None]:
    """Load Vosk + Piper, measuring RSS at each step. Returns (wav_path, piper_voice)."""
    print("\n=== RAM + model load ===")
    base = _rss_kb()
    print(f"  baseline RSS            {_mb(base)}")
    out.add("ram", "baseline RSS", _mb(base))

    wav_path = None
    piper_voice = None

    # ---- Piper ----
    try:
        from piper.voice import PiperVoice
        model_path = Path(settings.piper_model_path)
        if not model_path.exists():
            # fall back to any .onnx in models/piper/
            cand = sorted(Path("models/piper").glob("*.onnx")) if Path("models/piper").is_dir() else []
            model_path = cand[0] if cand else model_path
        if not model_path.exists():
            raise FileNotFoundError(f"no Piper voice at {settings.piper_model_path} or models/piper/*.onnx")
        t0 = time.monotonic()
        piper_voice = PiperVoice.load(str(model_path))
        load_s = time.monotonic() - t0
        after = _rss_kb()
        d = None if (after is None or base is None) else after - base
        tier = ("low" if "low" in model_path.name else "medium" if "medium" in model_path.name
                else "high" if "high" in model_path.name else "?")
        print(f"  Piper loaded           {_mb(after)}   (+{_mb(d)}, {load_s:.1f}s)   voice={model_path.name} tier={tier}")
        out.add("ram", "after Piper", f"{_mb(after)} (+{_mb(d)})")
        out.add("piper", "voice", f"{model_path.name} ({tier})",
                "WARN heavy tier for a Zero 2 W" if tier in ("medium", "high") else "")
    except Exception as e:
        print(f"  Piper                  SKIP  ({e})")
        out.add("piper", "load", "SKIP", str(e))

    # ---- Vosk ----
    try:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)  # silence the C-library decoding-params spam
        vp = Path(settings.vosk_model_path)
        if not vp.exists():
            raise FileNotFoundError(f"no Vosk model at {vp}")
        t0 = time.monotonic()
        vosk_model = Model(str(vp))
        load_s = time.monotonic() - t0
        after = _rss_kb()
        d = None if (after is None or base is None) else after - base
        print(f"  Vosk loaded            {_mb(after)}   (+{_mb(d)}, {load_s:.1f}s)")
        out.add("ram", "after Vosk", f"{_mb(after)} (+{_mb(d)})")
    except Exception as e:
        print(f"  Vosk                   SKIP  ({e})")
        out.add("vosk", "load", "SKIP", str(e))
        vosk_model = None

    avail = _mem_available_kb()
    if avail is not None:
        verdict = "OK" if avail > 60_000 else "WARN low headroom"
        print(f"  MemAvailable (peak)    {_mb(avail)}   {verdict}")
        out.add("ram", "MemAvailable @ load", _mb(avail), verdict)

    # ---- Piper synth timing (to buffer, no playback) ----
    if piper_voice is not None:
        try:
            t0 = time.monotonic()
            chunks = list(piper_voice.synthesize(sentence))
            synth_s = time.monotonic() - t0
            import numpy as np
            audio = np.concatenate([c.audio_int16_array for c in chunks])
            sr = chunks[0].sample_rate
            audio_s = len(audio) / sr
            xrt = synth_s / audio_s if audio_s else float("inf")
            verdict = "OK real-time" if xrt < 1.0 else f"WARN {xrt:.2f}x — slower than real-time"
            print(f"  Piper synth            {synth_s:.2f}s for {audio_s:.1f}s audio   = {xrt:.2f}x realtime   {verdict}")
            out.add("piper", "synth x realtime", f"{xrt:.2f}x  ({synth_s:.2f}s / {audio_s:.1f}s)", verdict)
            # stash a WAV for the STT stage
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
                w.writeframes(audio.astype("<i2").tobytes())
            wav_path = Path(os.environ.get("TMPDIR", "/tmp")) / "g2_bench_tts.wav"
            wav_path.write_bytes(buf.getvalue())
        except Exception as e:
            print(f"  Piper synth            SKIP  ({e})")
            out.add("piper", "synth", "SKIP", str(e))

    # ---- Vosk transcription timing ----
    if vosk_model is not None:
        try:
            from vosk import KaldiRecognizer
            src = wav_path
            if src is None:  # no Piper WAV — time the recognizer on generated noise
                import numpy as np
                sr = 16000
                noise = (np.random.default_rng(0).normal(0, 2000, sr * 4)).astype("<i2")
                buf = io.BytesIO()
                with wave.open(buf, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
                    w.writeframes(noise.tobytes())
                src = Path(os.environ.get("TMPDIR", "/tmp")) / "g2_bench_noise.wav"
                src.write_bytes(buf.getvalue())
            wf = wave.open(str(src), "rb")
            rate = wf.getframerate()
            rec = KaldiRecognizer(vosk_model, rate)
            rec.SetWords(False)
            audio_s = wf.getnframes() / rate
            t0 = time.monotonic()
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                rec.AcceptWaveform(data)
            text = json.loads(rec.FinalResult()).get("text", "")
            stt_s = time.monotonic() - t0
            xrt = stt_s / audio_s if audio_s else float("inf")
            verdict = "OK real-time" if xrt < 1.0 else f"WARN {xrt:.2f}x"
            print(f"  Vosk transcribe        {stt_s:.2f}s for {audio_s:.1f}s audio   = {xrt:.2f}x realtime   {verdict}")
            if wav_path is not None:
                exp = set(w.strip(".,").lower() for w in sentence.split())
                got = set(text.split())
                acc = len(exp & got) / len(exp) if exp else 0.0
                print(f"  Vosk transcript        {text!r}")
                print(f"  Vosk word recall       {acc:.0%} of the spoken sentence")
                out.add("vosk", "word recall (Piper->Vosk)", f"{acc:.0%}")
            out.add("vosk", "transcribe x realtime", f"{xrt:.2f}x  ({stt_s:.2f}s / {audio_s:.1f}s)", verdict)
        except Exception as e:
            print(f"  Vosk transcribe        SKIP  ({e})")
            out.add("vosk", "transcribe", "SKIP", str(e))

    return wav_path, piper_voice


def sec_all_voices(out: Row, sentence: str) -> None:
    """Synth timing for every voice in models/piper/ — the Zero 2 W low-vs-medium call."""
    print("\n=== Piper voices (synth x realtime) ===")
    d = Path("models/piper")
    voices = sorted(d.glob("*.onnx")) if d.is_dir() else []
    if not voices:
        print("  SKIP  (no models/piper/*.onnx)")
        return
    try:
        from piper.voice import PiperVoice
        import numpy as np
    except Exception as e:
        print(f"  SKIP  ({e})")
        return
    for mp in voices:
        try:
            v = PiperVoice.load(str(mp))
            t0 = time.monotonic()
            chunks = list(v.synthesize(sentence))
            synth_s = time.monotonic() - t0
            audio = np.concatenate([c.audio_int16_array for c in chunks])
            audio_s = len(audio) / chunks[0].sample_rate
            xrt = synth_s / audio_s if audio_s else float("inf")
            verdict = "OK" if xrt < 1.0 else f"WARN {xrt:.2f}x"
            print(f"  {mp.name:<28} {xrt:.2f}x realtime   ({synth_s:.2f}s / {audio_s:.1f}s)   {verdict}")
            out.add("voices", mp.name, f"{xrt:.2f}x", verdict)
            del v
        except Exception as e:
            print(f"  {mp.name:<28} SKIP  ({e})")

def sec_claude(out: Row, samples: int) -> None:
    print("\n=== Claude API round-trip ===")
    key = settings.anthropic_api_key
    if not key:
        print("  SKIP  (ANTHROPIC_API_KEY not set)")
        out.add("claude", "round-trip", "SKIP", "no API key")
        return
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key, timeout=settings.request_timeout_s)
        lat = []
        for i in range(samples):
            t0 = time.monotonic()
            client.messages.create(model=settings.claude_model, max_tokens=16,
                                   messages=[{"role": "user", "content": "ping"}])
            lat.append(time.monotonic() - t0)
            print(f"  #{i + 1}  {lat[-1] * 1000:.0f} ms")
        lat.sort()
        p50 = statistics.median(lat)
        p95 = lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))]
        print(f"  p50 {p50 * 1000:.0f} ms   p95 {p95 * 1000:.0f} ms   min {lat[0] * 1000:.0f}   max {lat[-1] * 1000:.0f}   model={settings.claude_model}")
        out.add("claude", "round-trip p50", f"{p50 * 1000:.0f} ms")
        out.add("claude", "round-trip p95", f"{p95 * 1000:.0f} ms")
    except Exception as e:
        print(f"  SKIP  ({e})")
        out.add("claude", "round-trip", "SKIP", str(e))

def sec_stress(out: Row, seconds: int) -> None:
    print(f"\n=== CPU load / thermal ({seconds}s) ===")
    if not LINUX:
        print("  SKIP  (not Linux)")
        out.add("thermal", "under load", "SKIP", "not Linux")
        return
    temp0 = _sh("vcgencmd", "measure_temp") or _sh("cat", "/sys/class/thermal/thermal_zone0/temp")
    print(f"  temp before            {temp0}")
    # start load: prefer stress-ng, else N python busy loops
    procs = []
    n = os.cpu_count() or 4
    if _sh("which", "stress-ng"):
        procs.append(subprocess.Popen(["stress-ng", "--cpu", str(n), "--timeout", f"{seconds}s"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    else:
        print("  (stress-ng not installed — using python busy loops; `sudo apt install stress-ng` for a truer test)")
        for _ in range(n):
            procs.append(subprocess.Popen([sys.executable, "-c",
                                           f"import time;e=time.time()+{seconds}\nwhile time.time()<e: pass"]))
    # sample responsiveness + temp during the load
    jitter = []
    tmax = 0.0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        t0 = time.monotonic()
        time.sleep(0.1)
        jitter.append((time.monotonic() - t0 - 0.1) * 1000)  # ms over the requested sleep
        t = _sh("cat", "/sys/class/thermal/thermal_zone0/temp")
        if t and t.isdigit():
            tmax = max(tmax, int(t) / 1000)
    for p in procs:
        try: p.wait(timeout=5)
        except Exception: p.kill()
    temp1 = _sh("vcgencmd", "measure_temp") or f"{tmax:.1f}'C (zone0)"
    thr = _sh("vcgencmd", "get_throttled")
    j = max(jitter) if jitter else 0.0
    jverdict = "OK" if j < 250 else "WARN scheduler starving the main loop"
    print(f"  temp after             {temp1}   (peak zone0 {tmax:.1f} C)")
    print(f"  throttled flags        {thr}")
    print(f"  sleep-jitter (max)     {j:.0f} ms over a 100 ms sleep   {jverdict}")
    out.add("thermal", "temp after load", f"{temp1} (peak {tmax:.1f}C)")
    out.add("thermal", "throttled", thr or "n/a",
            "WARN" if (thr and thr != "throttled=0x0") else "OK")
    out.add("thermal", "main-loop jitter", f"{j:.0f} ms", jverdict)

def sec_serial(out: Row) -> None:
    print("\n=== serial port ===")
    for label, port in (("robot link", settings.serial_port),
                        ("vision link", settings.vision_serial_port)):
        exists = Path(port).exists()
        print(f"  {label:<12} {port:<16} {'present' if exists else 'absent (BiBoard/camera not wired yet)'}")
        out.add("serial", label, f"{port} {'present' if exists else 'absent'}")

# ------------------------------------------------------------------ main ------
def main() -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.benchmark_pi")
    ap.add_argument("--skip-api", action="store_true", help="no Claude round-trips")
    ap.add_argument("--skip-stress", action="store_true", help="no CPU-load / thermal test")
    ap.add_argument("--api-samples", type=int, default=5)
    ap.add_argument("--stress-seconds", type=int, default=60)
    ap.add_argument("--sentence", default=SENTENCE)
    ap.add_argument("--all-voices", action="store_true",
                    help="synth-time every models/piper/*.onnx (low vs medium on the Zero 2 W)")
    args = ap.parse_args()

    print(f"g2 pi benchmark   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    out = Row([])
    sec_system(out)
    sec_ram_and_voice(out, args.sentence)
    if args.all_voices:
        sec_all_voices(out, args.sentence)
    if not args.skip_api:
        sec_claude(out, args.api_samples)
    if not args.skip_stress:
        sec_stress(out, args.stress_seconds)
    sec_serial(out)

    print("\n" + "=" * 72 + "\nSUMMARY\n" + "=" * 72)
    w = max((len(f"{s}/{m}") for s, m, _, _ in out.rows), default=20)
    for s, m, v, verdict in out.rows:
        print(f"  {f'{s}/{m}':<{w}}  {str(v):<34}  {verdict}")
    warns = [r for r in out.rows if str(r[3]).startswith("WARN")]
    skips = [r for r in out.rows if str(r[2]) == "SKIP"]
    print(f"\n  {len(warns)} warning(s), {len(skips)} skipped section(s).")
    if warns:
        print("  warnings:")
        for s, m, _, verdict in warns:
            print(f"    - {s}/{m}: {verdict}")


if __name__ == "__main__":
    main()
