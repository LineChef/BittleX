# Hardware diagnostics / black-box logging — plan

Goal: when something unknown goes wrong on the real robot, have enough recorded
context to figure out what happened without reproducing it. Drafted 2026-09-05,
pre-hardware.

---

## What exists today

- **Per-module `logging`** — `logging.getLogger("g2.link")`, `"g2.link.recovery"`,
  etc. Goes to stderr/console. Not captured, not correlated, no session index.
- **`run_gait --log`** — per-tick CSV (t, rpy, gyro, 8 joint deg, and now
  `guard_state / hottest_j / hottest_frac / duty_s`). Gait loop only.
- **`benchmark_pi.py`** — one-shot timing/thermal/RAM harness, not a run logger.
- **`sysid_collect.py`** — logs commanded joint angles for offline sysid.

**Gaps:** nothing unified across subsystems, no session manifest, no severity
taxonomy, no pre-incident telemetry, no way to line up a vision event against a
gait event against a link event, no crash context.

---

## Design — four pieces

### 1. Structured session log — `pi_pipeline/diag/`

One JSONL file per run: `~/g2_logs/<session_id>/events.jsonl`.
`session_id` = ISO-ish timestamp + short random (`20260905T160312_a4f1`).

Tiny shared API:

```python
from pi_pipeline.diag import diag
diag.event("gait", "WARN", "servo.stall", joint=2, err_deg=24.1, held_s=1.5)
```

Fields per line: `wall_ts, mono_t, session_id, subsystem, level, name, **kv`.
Levels: `DEBUG / INFO / WARN / ERROR / FATAL`.

A `logging.Handler` bridge mirrors every existing `g2.*` logger record into the
same JSONL, so current `log.info(...)` calls are captured for free — no rewrite,
just add the handler at startup.

### 2. Black-box ring buffer

Fixed-size in-memory deque holding the **last ~15 s** of high-rate telemetry,
sampled every control tick:

- IMU roll/pitch/yaw + gyro
- commanded joint deg (8) + joint feedback deg (8, when `readAllFeedbackFast()`
  is wired) + tracking error
- thermal guard: state, per-joint heat estimate, duty timer
- link: bytes in/out, timeouts, reconnects since last sample
- loop latency (policy step ms, tick jitter)
- battery voltage, Pi SoC temp + throttle flags

On any of {`ERROR`/`FATAL` event, `fall.detected`, `loop.stall`,
`servo.thermal_cooldown`, `link.lost`} → flush the ring to
`<session_id>/blackbox_<ts>.csv`. That's the ~15 s *leading up to* the incident,
which is what actually matters when the cause is unknown.

### 3. Session manifest

On startup write `<session_id>/manifest.json`:

- git SHA (`git rev-parse HEAD`), dirty flag
- OpenCat firmware version (`?` query over the link)
- config snapshot (`pi_pipeline.config.settings` as dict, key redacted)
- policy path + file hash; `deploy_map` calibration (`SERVO_SIGN`,
  `SERVO_OFFSET_DEG`)
- battery voltage at start, Pi model, ambient/SoC temp
- CLI args, hostname, uptime

Rules out "wrong build / wrong calibration / dead battery" in two seconds.

### 4. Watchdog + heartbeat

A supervisor thread:

- logs `diag.event("sys", "INFO", "heartbeat", loop_hz=..., miss=...)` every 1 s
- if the control loop misses ticks for > ~250 ms (hung ONNX, serial stall, Pi
  throttle) → log `loop.stall` with the last ring state, flush the black box,
  send `d` (safe stop)
- wraps the main loop in a try/except → unhandled exception becomes a `FATAL`
  event + black-box flush + `d` before exit (never leave servos loaded on a
  crash)

---

## Failure taxonomy — predefined events

Anticipated failure modes, each emitted with structured context so one call
gives you the event *and* the black box:

| Event | Fired by | Context |
|---|---|---|
| `link.lost` / `link.reconnect` | `serial_link` | consecutive timeouts, gap ms |
| `imu.parse_fail` / `imu.stale` | `run_gait` | raw line, consecutive misses |
| `servo.stall` | `thermal_guard` | joint, tracking error, held s |
| `servo.thermal_cooldown` | `thermal_guard` | reason, per-joint heat, duty s |
| `fall.detected` | `recovery` | roll/pitch, classified body state |
| `onnx.overrun` | `residual_policy` | step ms vs budget |
| `battery.sag` | watchdog | voltage, threshold |
| `pi.thermal_throttle` | watchdog | `vcgencmd get_throttled` bits, SoC temp |
| `loop.stall` | watchdog | last tick age, last ring row |
| `wifi.drop` | watchdog / voice | RSSI, ping RTT |

---

## Decision events — *why* G2 did something

Debugging behaviour needs the *reason*, not just the action. Convention:

- **State machines stay pure** (no `diag` import — keeps them unit-testable) but
  each exposes a `last_reason: str` explaining its most recent `update()`.
  Implemented: `behavior/idle_posture.py` (`IdlePosture`),
  `behavior/mode_controller.py` (`ModeController`). To add: `Explorer`,
  `RecoveryFSM`, vision `avoidance`.
- **The driving loop logs the transition** with the reason + the inputs that
  produced it, only when something actually changes:

  ```python
  new = ip.update(person_present=seen, safe_to_rest=level)
  if new != prev:
      diag.event("behavior", "INFO", "posture.transition",
                 **{"from": prev[0].value, "to": new[0].value,
                    "action": new[1].value, "because": ip.last_reason})
  ```

Reads back as a timeline: `posture sit→resting because "160s sat >= 90s"` ·
`mode idle→explore because "45s quiet >= idle_secs_before_explore(45)"` ·
`reflex cliff_stop because "edge at 0.18 m"`. `diag summarize` already lists
every WARN+ event; INFO-level decision events show in `diag tail` and full
`replay`, and can be promoted to WARN for a noisy debugging session.

---

## Post-hoc tooling — `python -m pi_pipeline.diag`

- `diag summarize <session>` — timeline of WARN+ events, duration, incident
  count, manifest highlights
- `diag replay <session> [--around <ts>]` — dump / plot a black-box window
  around an incident (reuse `real_vs_sim` plotting if present)
- `diag tail` — live-follow `events.jsonl` during a run
- `diag sync <session>` — rsync a session dir to the laptop

---

## Storage / transport

- Local: `~/g2_logs/<session_id>/` — `events.jsonl`, `manifest.json`,
  `blackbox_*.csv`, plus the existing `run_gait` per-tick CSV as one more file.
- Rotation: keep last N sessions or M MB, whichever first.
- Optional live view: stream events over Wi-Fi (UDP/line-JSON) to a laptop
  listener while a run is happening.

---

## Phasing

- **Phase 1 — now, pre-hardware (~1–2 days, most of the value):**
  build `pi_pipeline/diag/` — JSONL logger + `logging.Handler` bridge + ring
  buffer class + manifest writer + `diag summarize/replay/tail`. All
  unit-testable with synthetic data. Retrofit `run_gait`, `thermal_guard`,
  `serial_link`, `recovery` to emit the taxonomy events. Fold the existing
  `run_gait --log` CSV in as a ring-buffer source.
- **Phase 2 — at bring-up:** watchdog/heartbeat thread, dump-on-incident wiring,
  battery + Pi-thermal sampling, the exception hook. Validate the black box
  actually captures a real fall / link drop.
- **Phase 3 — as needed:** live Wi-Fi stream + laptop listener, longer-term
  trend rollups across sessions.

Phase 1 is not hardware-gated and pairs naturally with the ONNX-export /
Pi-bring-up work already queued.
