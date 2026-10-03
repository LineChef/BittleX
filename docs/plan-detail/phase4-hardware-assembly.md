# Phase 4 — Hardware assembly (detail)

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> Phase 4 (hardware assembly and bring-up). Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## Phase 4 — Hardware assembly

- [x] **Assemble Bittle X V2 — done 2026-09-28.** Pi+PiSugar wiring/bring-up
      (Steps 2-4, `blueprints/biboard-pi-connector.md`) and the mount
      redesign (Step 5) are now unblocked — BiBoard exists.
- [x] **Check servo calibration — redone for real, 2026-09-29, post-reflash.**
      The 2026-09-28 zero-point calibration below was wiped by the same-night
      firmware reflash (`esptool erase_flash`, required to fix the
      camera-kills-IMU bug — see `docs/hardware/petoi-firmware-reference.md`).
      Nothing meaningful was lost (it was a minimal power-on-on-its-side
      calibration, no full ROM pass). Redone properly this time via the
      Petoi Desktop App's Joint Calibrator + the L-shaped bracket, one leg
      at a time; verified with `kbalance` (all four feet level both times
      it was sent). Full procedure + a finding worth knowing (the bracket
      step targets frame-relative leg angle, not floor contact — front feet
      sitting slightly off the ground during that step is expected
      geometry, not miscalibration) in `blueprints/calibration.md`.
      Voice module's English-default fix (`XAc`/`XAb`/`XAa`, also
      EEPROM-wiped by the erase) reapplied same day — confirmed recurred
      (stuck on Chinese again, same as the pre-reflash incident) and fixed
      the same way; verified live via voice ("play sound" + an actual
      English command).
      Prior finding (2026-09-28, pre-reflash): the stock `vtF` ("step") gait stumbles
      toward the back-right leg, 100% reproducible every run; every other
      tested command (postures, other gaits) looked normal. Ruled out so
      far: by-hand resistance on the back-right shoulder/knee (normal, no
      binding/gear-protection stiffness); individual per-joint `m<idx>`
      nudges on all 8 leg joints + head via `check_serial send` (all
      normal, no stuck/defective servo); `kbalance` (the documented
      calibration-check pose, all 8 joints to a symmetric 30°) — back-right
      leg sat symmetric with the other three, ruling out a per-leg
      zero-point offset too; **`kwkF`** (the gait the trained policy is
      actually layered on) — back-right leg looked normal, no stumble.
      **Conclusion: isolated to `vtF` specifically, does not affect `wkF`.**
      Deprioritized — `vtF` isn't used anywhere in our deployment path, so
      this is parked as an unexplained quirk of that one stock gait rather
      than something to keep chasing; revisit only if it turns out to
      correlate with something that does matter (e.g. shows up again once
      the Pi/payload is mounted, or in `wkF` under load/turns).
- [ ] Get it moving on stock firmware first, before any custom code — base
      firmware functions tested 2026-09-28 (see calibration finding above).
- [x] Set up the Pi Zero 2 WH: pre-configure Wi-Fi + SSH in Raspberry Pi Imager
      (headless), confirm SSH access. **Done (2026-09-02)** — card flashed
      (`~/pi-setup/flash-pi.sh`, custom hostname/user/Wi-Fi/SSH-key baked into
      `custom.toml` rather than the Imager GUI), SSH confirmed as
      `<user>@g2pi.local`. Superseded by the full bring-up, `[x]`'d in Phase 6
      below.
  - Full researched runbook + open-question answers in
    [`docs/guides/pi-bring-up.md`](../guides/pi-bring-up.md): flash Bookworm
    64-bit Lite, kill Wi-Fi power-save, zram+swapfile, disable-BT for the PL011
    UART, deploy `pi_pipeline` on ARM, then `benchmark_pi.py` (Vosk / Piper /
    Claude-API / RAM). PiSugar **S** = dumb UPS: no I²C, no battery %, power-
    present only.
- [ ] Mount the Pi; test power and serial **independently** (power can work while
      serial doesn't). Per Petoi's Raspberry Pi serial docs:
  - Power the Pi from the PiSugar S, not the BiBoard. Wire BiBoard → Pi
    data-only (RX/TX/GND), Pi 5 V unconnected. See [`docs/hardware/pi-power.md`](../hardware/pi-power.md).
  - [x] Install the 5-pin Pi socket on BiBoard V1 — **soldered 2026-09-29**
    (`blueprints/biboard-pi-connector.md` Step 2). Still need: the actual
    RX/TX/GND jumpers to the Pi (Step 3), and use Petoi's back-cover STL with
    the Pi cutout.
  - Petoi's official Pi standoff bracket (`Pi_StandOffRegular.stl`) does
    **not** work as-is for this stack — see status line below.
- [ ] **Build: Pi+PiSugar mount to the frame — power confirmed working
      2026-09-17, mount mechanism not yet solved, deferred until the frame
      physically arrives.** This is now a status line only — the full
      findings (PiSugar orientation fix, confirmed pogo-pin/header contact
      mechanism, why the corner-clip and screw-through-bracket approaches
      were both ruled out, and the candidate options being weighed) live in
      [`blueprints/biboard-pi-connector.md`](../../blueprints/biboard-pi-connector.md)
      (the single build manual, Steps 1-5) and the
      [Pi Stack Build Guide](https://claude.ai/artifact/LGfD7LCP1KdUswz9DJCm8M)
      — that's the canonical reference, not this checklist.
  - Step 1 (Pi+PiSugar) is done and needed no mount. **Step 2 (solder BiBoard's
    5-pin Pi header) done 2026-09-29** — the frame-unassembled blocker that held
    up Steps 2-4 is resolved (frame's been assembled since 2026-09-28). Steps
    3-4 (actual jumper wiring, dry-fit) still open. **Step 5 (mount): interim
    solution in place, 2026-09-29** — PiSugar's own official case
    (`pisugar_case_shell_xl`, the 1200 mAh variant) + a modified stock back
    cover, velcroed to the outside of the lid rather than enclosed inside it
    (measured: the case is 31mm thick, the cover's internal cavity is only
    18.6mm deep — doesn't fit inside, so this sidesteps rather than solves
    that). Not the final mount; parts were 3D-printing at time of writing.
    Full detail: `blueprints/biboard-pi-connector.md`.
  - Cover modified (button/switch + SD card access) rather than on hold now.
  - Screws to buy (M2 pan-head self-tapping assortment) — see the build doc's
    "Screws to buy."
- [ ] `sudo raspi-config` → Interface Options → Serial Port → disable the serial
      login shell, enable the serial hardware → reboot.
- [ ] Disable the Pi's 1-wire interface (GPIO 4 reset-signal conflict).
- [ ] Disable Wi-Fi power-save (`sudo iw wlan0 set power_save off`) proactively —
      the `brcmfmac` power-save bug drops SSH under CPU load and is a nightmare to
      diagnose later.
- [x] On the BiBoard: serial command `XS` to enable Serial-2 working mode —
      **done 2026-09-30** (over USB; `X?` shows the module table `S=1`, persisted
      across resets; a reflash wipes it, so redo `XS` after any reflash).
- [ ] Serial device: likely `/dev/ttyS0` on the Pi Zero 2 W (Pi-3-family SoC);
      confirm once wired.
- [ ] Use `ardSerial.py` from the OpenCat repo as the reference serial commander.
- [x] Set up the AI Vision Camera Module: mount at the head, connect to the Grove
      socket, upload firmware via Petoi Desktop App or Arduino IDE. **Mounted +
      connected 2026-09-29** — firmware/model upload was already done pre-arrival
      (bench bring-up, Phase 8). Physically tight fit getting the connector into
      the Grove socket at the head — worth noting for anyone redoing this later.
      Done despite the Pi+PiSugar mount mechanism (below) still being unresolved;
      that decision is now more constrained since the camera's cable routing at
      the same head-adjacent edge is already committed.
