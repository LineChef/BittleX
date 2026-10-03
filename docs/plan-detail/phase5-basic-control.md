# Phase 5 — Basic programming & control (detail)

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> Phase 5. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## Phase 5 — Basic programming & control

**Status:** the serial control layer is built and tested (mock/offline) —
`pi_pipeline/link/`. `SerialLink` (lazy open, auto-reconnect, non-raising
`send()`), `opencat.py` (command-string builders + `is_safe()` calibration
block), and `check_serial.py` diagnostics. `voice/SerialActuator` now goes
through it. Command reference and a hardware bring-up checklist are in
`pi_pipeline/link/README.md`.

- [x] Send movement commands from Python — `link.opencat.skill()` →
      `SerialLink.send()`; `check_serial send <cmd>` / `skills` / `rest`.
- [x] OpenCat command structure captured — `k<skill>`, `m<idx> <deg>`,
      `b<tone> <ms>`, `d` (rest), `XS` (Serial-2). Provisional: `g`/`v`/`V`/`p`.
      A **battery-voltage query token still needs finding** in the firmware
      serial parser.
- [ ] Hardware bring-up: `check_serial ports` → set `G2_SERIAL_PORT`; enable
      Serial-2 on the BiBoard; `check_serial ping` / `skills` to confirm.
- [x] Test the vision module's on-device detection via the SenseCraft AI Model
      Assistant web debug GUI. **Done 2026-09-05** — stock classification model
      deployed, live feed + labels confirmed.
- **Camera → Pi is over USB, not the Grove/GPIO pins** (decided 2026-09-05 from
      the Seeed wiki): the Grove 4-pin connector is **I²C** (`0x62`), not UART.
      Link the module USB-C → the Pi's USB *data* port (Pi Zero 2 W: the *inner*
      micro-USB) → it enumerates as `/dev/ttyACM0`, same SSCMA AT/JSON protocol,
      `VISION_SERIAL_BAUD` 921600. `SerialDetectionFeed` sends `AT+INVOKE=-1,0,1`
      on open (the module doesn't self-stream) and `AT+BREAK` on close.
