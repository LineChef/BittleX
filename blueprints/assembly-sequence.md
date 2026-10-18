# Assembly sequence

The order G2 was built in, with the record for each step. Follow it top to bottom to reproduce the hardware; each row links to the page that holds the detail. Dates are when the step was done on this robot. For the current state of the hardware see [`../docs/hardware/as-built.md`](../docs/hardware/as-built.md).

| # | Step | Done | Record |
|---|---|---|---|
| 1 | Mount the PiSugar S under the Pi Zero 2 W (pogo-pin contact, header stays free) | 2026-09-18 | [`build-logs/pi-biboard-build-notes.md`](../docs/hardware/build-logs/pi-biboard-build-notes.md) Step 1 |
| 2 | Assemble the Bittle X V2 frame, servos and BiBoard from Petoi's kit | 2026-09-28 | Petoi's assembly guide; notes in [`../docs/plan-detail/phase4-hardware-assembly.md`](../docs/plan-detail/phase4-hardware-assembly.md) |
| 3 | Erase and reflash the BiBoard with the current official OpenCat firmware | 2026-09-29 | [`../docs/hardware/petoi-firmware-reference.md`](../docs/hardware/petoi-firmware-reference.md), [`../docs/hardware/calibration-and-bringup-research.md`](../docs/hardware/calibration-and-bringup-research.md) |
| 4 | Calibrate the eight leg servos with the bracket and verify with `kbalance` | 2026-09-29 | [`calibration.md`](calibration.md) |
| 5 | Prepare the BiBoard's 5-pin Pi socket (solder the header) | about 2026-09-30 | [`build-logs/pi-biboard-build-notes.md`](../docs/hardware/build-logs/pi-biboard-build-notes.md) Step 2 |
| 6 | Wire Pi to BiBoard: TX, RX and GND only (data, no 5 V) | 2026-09-30 | [`build-logs/pi-biboard-build-notes.md`](../docs/hardware/build-logs/pi-biboard-build-notes.md) Step 3, [`wiring/g2-wiring-guide.html`](wiring/g2-wiring-guide.html) |
| 7 | Enable Serial-2 on the BiBoard (`XS`) and check the link (`check_serial ping`) | 2026-09-30 | [`../docs/guides/pi-bring-up.md`](../docs/guides/pi-bring-up.md) |
| 8 | Connect the camera module to the Pi's USB port | 2026-09-30 | [`../docs/vision/README.md`](../docs/vision/README.md) |
| 9 | Wire the I2S microphone and amplifier to the Pi header | mic 2026-10-03, speaker 2026-10-04 | [`build-logs/i2s-audio-build-log.md`](../docs/hardware/build-logs/i2s-audio-build-log.md) |
| 10 | Mount the Pi stack, camera, speaker and microphone on the back cover (interim mount) | 2026-09-29 to 2026-10-06 | [`mounting.md`](mounting.md) |
| 11 | Replace the front-left shoulder servo and re-run calibration | 2026-10-06 (calibration date not recorded) | [`calibration.md`](calibration.md) |

After the hardware is together: [`../docs/guides/bring-up-sequence.md`](../docs/guides/bring-up-sequence.md) is the ordered software and first-movement bring-up (run it with `python -m pi_pipeline.bringup`).

Not part of the build: the Petoi AI Head ([`../docs/planned/ai-head/`](../docs/planned/ai-head/README.md)) and the arm module ([`../docs/planned/robot-arm.md`](../docs/planned/robot-arm.md)). Its wiring, if it is ever added, is Part 2 of the wiring guide.
