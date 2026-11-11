# Assembly sequence

The order G2 was built in, with the record for each step. Follow it top to bottom to reproduce the hardware; each row links to the page that holds the detail. Dates are when the step was done on this robot. For the current state of the hardware see [`../docs/hardware/as-built.md`](../docs/hardware/as-built.md).

- 1: Step: Mount the PiSugar S under the Pi Zero 2 W (pogo-pin contact, header stays free)
- 2: Step: Assemble the Bittle X V2 frame, servos and BiBoard from Petoi's kit; See: Petoi's assembly guide
- 3: Step: Erase and reflash the BiBoard with the current official OpenCat firmware; See: [`../docs/hardware/petoi-firmware-reference.md`](../docs/hardware/petoi-firmware-reference.md), [`../docs/hardware/calibration-and-bringup-research.md`](../docs/hardware/calibration-and-bringup-research.md)
- 4: Step: Calibrate the eight leg servos with the bracket and verify with `kbalance`; See: [`calibration.md`](calibration.md)
- 5: Step: Prepare the BiBoard's 5-pin Pi socket (solder the header)
- 6: Step: Wire Pi to BiBoard: TX, RX and GND only (data, no 5 V); See: [`wiring/g2-wiring-guide.html`](wiring/g2-wiring-guide.html)
- 7: Step: Enable Serial-2 on the BiBoard (`XS`) and check the link (`check_serial ping`); See: [`../docs/guides/pi-bring-up.md`](../docs/guides/pi-bring-up.md)
- 8: Step: Connect the camera module to the Pi's USB port; See: [`../docs/vision/README.md`](../docs/vision/README.md)
- 9: Step: Wire the I2S microphone and amplifier to the Pi header
- 10: Step: Mount the Pi stack, camera, speaker and microphone in the Bittle X Pi add-on pod on the platform cover (an interim mount used a modified back cover); See: [`mounting.md`](mounting.md)
- 11: Step: Replace the front-left shoulder servo and re-run calibration; See: [`calibration.md`](calibration.md)

After the hardware is together: [`../docs/guides/bring-up-sequence.md`](../docs/guides/bring-up-sequence.md) is the ordered software and first-movement bring-up (run it with `python -m pi_pipeline.bringup`).

Not part of the build: the Petoi AI Head and the arm module. Its wiring, if it is ever added, is Part 2 of the wiring guide.
