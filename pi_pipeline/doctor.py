"""`python -m pi_pipeline.doctor` -- one-command bring-up readiness check.

Runs every "is this ready" check that's otherwise scattered across
`check_serial`, `check_audio`, `benchmark_pi`, and manual `.env` inspection, and
prints a green/red checklist. Exits non-zero if anything is a hard FAIL, so it
drops into a bring-up script.

    python -m pi_pipeline.doctor                # local checks
    python -m pi_pipeline.doctor --serial       # also handshake the BiBoard
    python -m pi_pipeline.doctor --json         # machine-readable

Checks: .env completeness, Anthropic key validity + expiry, model files
(Vosk / Piper / gait ONNX), Python deps, serial port, audio devices, free disk.
`--serial` adds a passive handshake -- port opens, a `?` banner, a `P` voltage
readback -- reads only, nothing that moves the robot, safe to run any time.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys

OK, WARN, FAIL = "ok", "warn", "fail"
_MARK = {OK: "PASS", WARN: "WARN", FAIL: "FAIL"}


def _r(name, status, detail=""):
    return {"name": name, "status": status, "detail": detail}


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def _check_env(s) -> list:
    out = [_r(".env present", OK if os.path.exists(".env") else WARN,
              "" if os.path.exists(".env") else "no .env at repo root (copy .env.example)")]
    out.append(_r("ANTHROPIC_API_KEY set",
                  OK if s.anthropic_api_key else FAIL,
                  "" if s.anthropic_api_key else "voice conversation won't start"))
    for label, val, default in (
        ("VOSK_MODEL_PATH", s.vosk_model_path, "models/vosk"),
        ("PIPER_MODEL_PATH", s.piper_model_path, "models/piper/en_US-ryan-low.onnx"),
        ("G2_SERIAL_PORT", s.serial_port, "/dev/serial0"),
    ):
        out.append(_r(f"{label}", OK, f"{val}{'  (default)' if val == default else ''}"))
    return out


def _check_key_expiry(s) -> list:
    lvl, msg = s.api_key_expiry_status()
    status = {"ok": OK, "warn": WARN, "expired": FAIL, "unset": WARN,
              "malformed": WARN}.get(lvl, WARN)
    detail = msg or ("ANTHROPIC_API_KEY_EXPIRES not set -- add it as a reminder"
                     if lvl in ("unset", "malformed") else "valid")
    return [_r("API key expiry", status, detail)]


def _check_models(s) -> list:
    out = []
    vosk = s.vosk_model_path
    out.append(_r("Vosk model", OK if os.path.isdir(vosk) else WARN,
                  vosk if os.path.isdir(vosk) else f"{vosk} missing (voice mode only)"))
    piper = s.piper_model_path
    ok_piper = os.path.isfile(piper) and os.path.isfile(piper + ".json")
    out.append(_r("Piper voice", OK if ok_piper else WARN,
                  piper if ok_piper else f"{piper}(.json) missing (voice mode only)"))
    onnx = "rl_training/opencat-gym/trained/run20m_ppo.onnx"
    for cand in (onnx, "models/gait/run20m_ppo.onnx"):
        if os.path.isfile(cand):
            out.append(_r("Gait policy ONNX", OK, cand))
            break
    else:
        out.append(_r("Gait policy ONNX", WARN, "not found (export before the H1 run)"))
    return out


def _check_deps() -> list:
    out = []
    for mod, hard, why in (
        ("anthropic", True, "voice conversation"),
        ("numpy", True, "gait + vision"),
        ("vosk", False, "wake word + STT (voice mode)"),
        ("sounddevice", False, "mic/speaker I/O (voice mode)"),
        ("serial", False, "serial link (needs pyserial on the Pi)"),
        ("onnxruntime", False, "gait policy inference on the Pi"),
    ):
        present = _has(mod)
        out.append(_r(f"import {mod}", OK if present else (FAIL if hard else WARN),
                      "" if present else f"pip install -- needed for {why}"))
    return out


def _check_serial(s, ping: bool) -> list:
    port = s.serial_port
    exists = os.path.exists(port)
    out = [_r("serial port exists", OK if exists else WARN,
              port if exists else f"{port} not present (robot not wired yet?)")]
    if not (ping and exists and _has("serial")):
        return out
    # a passive handshake -- reads only, nothing that moves the robot, so this
    # is safe to run any time (mid-assembly, on the stand, before --bench even).
    try:
        from .link import opencat
        from .link.serial_link import SerialLink
        lk = SerialLink(port, s.serial_baud)
        if not lk.connect():
            out.append(_r("BiBoard responds", WARN, f"could not open {port}"))
            return out
        banner = lk.send(opencat.QUERY, read_reply=True)
        out.append(_r("BiBoard responds", OK if banner else WARN,
                      banner[:60] or "no reply to '?' -- check baud / wiring"))
        voltage = lk.send(opencat.PRINT_VOLTAGE, read_reply=True)
        v_ok = bool(voltage) and any(ch.isdigit() for ch in voltage)
        out.append(_r("battery voltage reads back", OK if v_ok else WARN,
                      voltage[:60] or "no reply to 'P' -- firmware may not be OpenCat, "
                                     "or the board isn't powered"))
        lk.close()
    except Exception as e:  # noqa: BLE001
        out.append(_r("BiBoard responds", WARN, f"{type(e).__name__}: {e}"))
    return out


def _check_audio() -> list:
    if not _has("sounddevice"):
        return [_r("audio devices", WARN, "sounddevice not installed")]
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        ins = [d for d in devs if d["max_input_channels"] > 0]
        outs = [d for d in devs if d["max_output_channels"] > 0]
        status = OK if (ins and outs) else WARN
        return [_r("audio devices", status, f"{len(ins)} in / {len(outs)} out")]
    except Exception as e:  # noqa: BLE001
        return [_r("audio devices", WARN, f"{type(e).__name__}: {e}")]


def _check_disk() -> list:
    free_gb = shutil.disk_usage(".").free / 1e9
    return [_r("free disk", OK if free_gb > 1.0 else WARN, f"{free_gb:.1f} GB")]


def run(*, ping_serial: bool = False) -> list:
    from .config import settings as s
    checks: list = []
    checks += _check_env(s)
    checks += _check_key_expiry(s)
    checks += _check_models(s)
    checks += _check_deps()
    checks += _check_serial(s, ping_serial)
    checks += _check_audio()
    checks += _check_disk()
    return checks


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.doctor")
    ap.add_argument("--serial", action="store_true", help="also ping the BiBoard")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    checks = run(ping_serial=args.serial)
    if args.json:
        print(json.dumps(checks, indent=2))
    else:
        width = max(len(c["name"]) for c in checks)
        for c in checks:
            line = f"  [{_MARK[c['status']]}]  {c['name']:<{width}}"
            if c["detail"]:
                line += f"   {c['detail']}"
            print(line)
        n_fail = sum(c["status"] == FAIL for c in checks)
        n_warn = sum(c["status"] == WARN for c in checks)
        print(f"\n{len(checks)} checks -- {n_fail} fail, {n_warn} warn")

    sys.exit(1 if any(c["status"] == FAIL for c in checks) else 0)


if __name__ == "__main__":
    main()
