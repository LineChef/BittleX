# Assembly sequence

The order G2 was built in, with the record for each step. Follow it top to bottom to reproduce the hardware; each row links to the page that holds the detail. Dates are when the step was done on this robot. For the current state of the hardware see [`../docs/hardware/as-built.md`](../docs/hardware/as-built.md).

- **1**: Step: Mount the PiSugar S under the Pi Zero 2 W (pogo-pin contact, header stays free); Done: 2026-09-18; Record: [`build-logs/pi-biboard-build-notes.md`](../docs/hardware/build-logs/pi-biboard-build-notes.md) Step 1
- **2**: Step: Assemble the Bittle X V2 frame, servos and BiBoard from Petoi's kit; Done: 2026-09-28; Record: Petoi's assembly guide
- **3**: Step: Erase and reflash the BiBoard with the current official OpenCat firmware; Done: 2026-09-29; Record: [`../docs/hardware/petoi-firmware-reference.md`](../docs/hardware/petoi-firmware-reference.md), [`../docs/hardware/calibration-and-bringup-research.md`](../docs/hardware/calibration-and-bringup-research.md)
- **4**: Step: Calibrate the eight leg servos with the bracket and verify with `kbalance`; Done: 2026-09-29; Record: [`calibration.md`](calibration.md)
- **5**: Step: Prepare the BiBoard's 5-pin Pi socket (solder the header); Done: about 2026-09-30; Record: [`build-logs/pi-biboard-build-notes.md`](../docs/hardware/build-logs/pi-biboard-build-notes.md) Step 2
- **6**: Step: Wire Pi to BiBoard: TX, RX and GND only (data, no 5 V); Done: 2026-09-30; Record: [`build-logs/pi-biboard-build-notes.md`](../docs/hardware/build-logs/pi-biboard-build-notes.md) Step 3, [`wiring/g2-wiring-guide.html`](wiring/g2-wiring-guide.html)
- **7**: Step: Enable Serial-2 on the BiBoard (`XS`) and check the link (`check_serial ping`); Done: 2026-09-30; Record: [`../docs/guides/pi-bring-up.md`](../docs/guides/pi-bring-up.md)
- **8**: Step: Connect the camera module to the Pi's USB port; Done: 2026-09-30; Record: [`../docs/vision/README.md`](../docs/vision/README.md)
- **9**: Step: Wire the I2S microphone and amplifier to the Pi header; Done: mic 2026-10-03, speaker 2026-10-04; Record: [`build-logs/i2s-audio-build-log.md`](../docs/hardware/build-logs/i2s-audio-build-log.md)
- **10**: Step: Mount the Pi stack, camera, speaker and microphone: first on the modified back cover (interim mount), then, from 2026-10-17, in the Bittle X Pi add-on pod on the platform cover; Done: interim 2026-09-29 to 2026-10-06; pod 2026-10-17; Record: [`mounting.md`](mounting.md)
- **11**: Step: Replace the front-left shoulder servo and re-run calibration; Done: 2026-10-06 (calibration date not recorded); Record: [`calibration.md`](calibration.md)

After the hardware is together: [`../docs/guides/bring-up-sequence.md`](../docs/guides/bring-up-sequence.md) is the ordered software and first-movement bring-up (run it with `python -m pi_pipeline.bringup`).

Not part of the build: the Petoi AI Head and the arm module. Its wiring, if it is ever added, is Part 2 of the wiring guide.
