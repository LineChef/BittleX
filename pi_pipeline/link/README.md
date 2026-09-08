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
| `recovery.py` | `RecoveryFSM` — the walk / catch / get-up switch. IMU roll+pitch in, a `RecoveryAction` out (`NONE` / `RECOVER` / `ROLL_THEN_RECOVER` / `DROP_RECOVER` / `SETTLE` / `GIVE_UP`). Pure logic, no serial I/O; `ACTION_COMMANDS` maps actions to `k…` strings. Once down, classifies the **fall pose** (`FallPose`: nose-down / tail-down / left / right side / back — `fsm.pose`) and fires the maneuver for it; on failure **escalates** `pose skill → roll+recover → dropRec → give up`. HW-gated bits (roll/pitch sign, one-sided `rc`, firmware auto-recover conflict) are `RecoveryConfig` flags with safe defaults + `HARDWARE-GATED` comments. |
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

Confirmed against `PetoiCamp/OpenCatEsp32` `OpenCat.h` `T_*` macros (2026-09-07 —
`docs/research/petoi-firmware-reference.md`) + project Phase 4 notes:

| Command | Meaning |
|---|---|
| `k<skill>` | perform a named skill — `kwkF`, `ksit`, `kbalance`, `ktrF`, `kcrF`, … |
| `m<idx> <deg> …` | move joint(s), chainable — `m0 30 8 -35` |
| `b<tone> <ms> …` | buzzer melody / beep — `b12 8 14 8` |
| `d` | rest: lie down, relax servos (ends a looping gait) |
| `P` | **print battery voltage** (`T_POWER`) |
| `j` / `j <idx>` | return all joint angles / one joint (`T_JOINTS`) |
| `f` | servo position feedback, if supported (`T_SERVO_FEEDBACK`) |
| `g` / `gU` / `gB` / `gc` | gyro toggle / force update / balance-on / calibrate IMU |
| `p` | pause (`T_PAUSE`) |
| `t` | tilt command (`T_TILT`) |
| `XS` | BiBoard: enter Serial-2 mode so it talks to the Pi |
| `krc` / `krl` | built-in get-up skills — self-right, and roll off the back. Firmware auto-runs `krc` once per IMU tick on a detected flip (`|roll|>85°`) **when gyro assist is on** — no retry/give-up logic of its own. See `docs/research/self-righting-research.md`. |

`v` / `V` is firmware **version**, not "print IMU" (earlier guess was wrong).
`?` (help/status) is still unverified against the firmware parser.

Blocked from the pipeline: `c`, `cd` (calibration / factory).

## Bring-up checklist (when hardware arrives)

1. `check_serial ports` → find the device, set `G2_SERIAL_PORT`.
2. On the BiBoard, enable Serial-2 mode (`XS`, or edit `OpenCat.h` + reflash).
3. `check_serial ping` → expect a firmware banner.
4. `check_serial send kbalance` → robot should stand and balance.
5. `check_serial skills` → watch it run the whole conversational set.
6. Point the voice loop at it: `python -m pi_pipeline.voice --mode text --actuator serial`.
