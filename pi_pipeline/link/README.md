# Link — serial to the BiBoard

The transport between the Pi and the robot's BiBoard (OpenCatEsp32 firmware).
Shared plumbing: `voice`'s `SerialActuator` uses it, `vision` maps avoidance
decisions to skills that go through it, and RL sim-to-real deployment will stream
joint commands over it.

## Modules

| File | Role |
|---|---|
| `serial_link.py` | `SerialLink` — lazy open, auto-reconnect on drop, `send()` never raises (logs + returns `""`). `list_ports()`. |
| `opencat.py` | Command-string builders (`skill`, `move_joints`, `beep`), constants (`REST`, `ENTER_SERIAL2_MODE`, `RECOVER`/`ROLL_OVER`/`BALANCE`/`STAND`), and `is_safe()` (blocks calibration). No I/O. |
| `recovery.py` | `RecoveryFSM` — the walk / catch / get-up switch. IMU roll+pitch in, a `RecoveryAction` out (`NONE` / `RECOVER` / `ROLL_THEN_RECOVER` / `SETTLE` / `GIVE_UP`). Pure logic, no serial I/O; `ACTION_COMMANDS` maps actions to `k…` strings. Fires the scripted `rc`/`rl` get-up skills once the robot is actually down; bounded retries then gives up. |
| `check_serial.py` | Diagnostics CLI. |

## Diagnostics

```bash
python -m pi_pipeline.link.check_serial ports        # list serial ports (works on any machine)
python -m pi_pipeline.link.check_serial ping         # open the configured port, read the banner + query
python -m pi_pipeline.link.check_serial send kbalance
python -m pi_pipeline.link.check_serial skills       # cycle every conversational skill, then rest
python -m pi_pipeline.link.check_serial rest         # 'd' — lie down, relax servos
```

Configured by `G2_SERIAL_PORT` / `G2_SERIAL_BAUD` (`.env`). Likely `/dev/ttyS0`
on the Pi Zero 2 W.

## Command reference (what we use)

Confirmed (docs.petoi.com/apis/serial-protocol, project Phase 4 notes):

| Command | Meaning |
|---|---|
| `k<skill>` | perform a named skill — `kwkF`, `ksit`, `kbalance`, `ktrF`, `kcrF`, … |
| `m<idx> <deg> …` | move joint(s), chainable — `m0 30 8 -35` |
| `b<tone> <ms> …` | buzzer melody / beep — `b12 8 14 8` |
| `d` | rest: lie down, relax servos (ends a looping gait) |
| `XS` | BiBoard: enter Serial-2 mode so it talks to the Pi |
| `krc` / `krl` | built-in get-up skills — self-right, and roll off the back. Firmware auto-runs `krc` on an IMU flip when gyro assist is on. See `docs/research/self-righting-research.md`. |

Provisional — verify against the OpenCatEsp32 serial parser before relying on
them: `g` (gyro toggle), `v` / `V` (print IMU), `p` (pause gait), `?` (query).
**Not found yet:** a battery-voltage query token — check the firmware.

Blocked from the pipeline: `c`, `cd` (calibration / factory).

## Bring-up checklist (when hardware arrives)

1. `check_serial ports` → find the device, set `G2_SERIAL_PORT`.
2. On the BiBoard, enable Serial-2 mode (`XS`, or edit `OpenCat.h` + reflash).
3. `check_serial ping` → expect a firmware banner.
4. `check_serial send kbalance` → robot should stand and balance.
5. `check_serial skills` → watch it run the whole conversational set.
6. Point the voice loop at it: `python -m pi_pipeline.voice --mode text --actuator serial`.
