# diag/

Diagnostics: leave enough behind that a hardware failure can be explained afterwards. Design and phases: [`../../docs/hardware/diagnostics.md`](../../docs/hardware/diagnostics.md).

| Module | Role |
|---|---|
| `core.py` | A structured per-session event log (`diag.event(...)`) plus a black-box ring buffer (`diag.attach_ring(RingBuffer(...))`); `summarize_session()` and `last_failure()` |
| `watchdog.py` | The control-loop heartbeat: the loop calls `wd.beat()` each tick; a stall past `stall_after_s` is logged and calls `on_stall()`, wired to a safe stop |
| `sysmon.py` | Battery and Pi-thermal sampling; degrades to `None` off the Pi |
| `crashwatch.py` | Heartbeat file, `faulthandler` output and a "clean exit" marker, read back at the next start, so a native crash (Vosk, PortAudio, onnxruntime) leaves a report in `crashes.jsonl` |

```bash
python -m pi_pipeline.diag list
python -m pi_pipeline.diag summarize [SESSION]       # default: the latest session
python -m pi_pipeline.diag last-failure [SESSION]
python -m pi_pipeline.diag tail [SESSION]
python -m pi_pipeline.diag replay SESSION --around HH:MM:SS [--window 5]
python -m pi_pipeline.diag sync SESSION DEST
python -m pi_pipeline.diag.crashwatch [N]             # the last N crash reports
```

Sessions are written under `~/g2_logs/`; `G2_CRASH_DIR` sets the crash folder. The voice assistant can answer questions about a session through the `diagnostics_query` tool, which calls the same two summary functions.
