# G2 as built

What G2 is made of, how it is connected, and what it weighs. This is the summary; each row links to the page that holds the detail and the evidence. The physical build record (wiring, soldering, mounting, calibration) is in [`../../blueprints/`](../../blueprints/README.md). What is working and what has been tested: [`../STATUS.md`](../STATUS.md). Parts that are bought or planned but not installed: [`../planned/`](../planned/README.md).

## Parts

| Part | What it is | Notes | Detail |
|---|---|---|---|
| Body | Petoi Bittle X V2, alloy feedback servos | 8 leg joints (shoulder and knee on each of four legs); no roll-axis actuation | [`specs.md`](specs.md) |
| Control board | Petoi BiBoard V1: ESP32-U4WDH, 4 MB flash, 520 KB SRAM | Runs OpenCat firmware; carries the IMU, a buzzer-only speaker and an offline voice-recognition module | [`petoi-firmware-reference.md`](petoi-firmware-reference.md) |
| IMU | ICM42670 (6-axis, no magnetometer) on the BiBoard | Stock stream is 5.0 Hz; `az` reads about 9.9 m/s² at rest | [`petoi-firmware-reference.md`](petoi-firmware-reference.md) |
| Computer | Raspberry Pi Zero 2 W (WH kit), 32 GB microSD | Debian 12 on the Pi; deployed to by `rsync` | [`../guides/pi-bring-up.md`](../guides/pi-bring-up.md) |
| Pi power | PiSugar S, 1200 mAh | Powers the Pi independently of the robot's pack; no battery readout (runtime is estimated from uptime); after a clean shutdown the Pi stays powered until the PiSugar switch is flipped by hand | [`pi-power.md`](pi-power.md) |
| Camera | Petoi AI Vision Camera Module (Grove Vision AI V2: Cortex-M55 + Ethos-U55) | On the Pi's USB (`/dev/ttyACM0`); runs the detector on itself and sends detections, not video; mounted at the front | [`../vision/README.md`](../vision/README.md) |
| Microphone | HiLetgo SPH0645 I²S MEMS breakout | On the Pi header; top of the case lid. Very quiet: digital gain is applied in software | [`../../blueprints/build-logs/i2s-audio-build-log.md`](build-logs/i2s-audio-build-log.md) |
| Speaker | NULLLAB NS4168 I²S amplifier with 3 W speaker | On the Pi header (shares the mic's I²S clock lines); at the very back | [`../../blueprints/build-logs/i2s-audio-build-log.md`](build-logs/i2s-audio-build-log.md) |
| Case | Modified Petoi back cover plus PiSugar's case, velcroed on | An interim mount: the case is thicker than the cover's cavity | [`../../blueprints/mounting.md`](../../blueprints/mounting.md) |

## Connections

| Link | How |
|---|---|
| Pi to BiBoard | 5-pin header (TX2, RX2, GND, +5V, +5V); only TX, RX and GND are wired, so the two power systems stay separate. UART at 115200 on `/dev/serial0`. BiBoard module flags set: Serial-2 and the onboard voice module |
| Pi to camera | USB |
| Pi to mic and amp | The 40-pin header, I²S (`googlevoicehat-soundcard` overlay) |
| Wi-Fi | Home network, with a phone hotspot saved as a backup |

Pinouts and the wire map: [`../../blueprints/wiring/g2-wiring-guide.html`](../../blueprints/wiring/g2-wiring-guide.html).

## Mass and balance

| | |
|---|---|
| Base robot | about 254 g |
| Payload (Pi, PiSugar, camera, speaker, mic, wiring, lid) | about 168 g, roughly 100 × 40 × 38 mm, centred on the spine |
| Whole robot | about 422 g |
| Front/rear share, standing | about 46% front, 54% rear (measured range roughly 44 to 50%) |

The measurements and the sim's payload model: [`specs.md`](specs.md) "Weight distribution, standing".

## Known hardware characteristics

- **Servo heat:** the leg servos overheat under sustained load; an estimator and cutback guard it. [`servo-thermal.md`](servo-thermal.md)
- **Self-righting:** the built-in self-right is limited; G2 is never put on his back, because the Pi and the BiBoard are exposed. [`self-righting.md`](self-righting.md)
- **Sensing limits:** a 5 Hz IMU, no gyro stream, no joint or foot feedback fast enough for the 80 Hz loop (position feedback reads at about 9 Hz). These shape what the walking policy can see.
- **Calibration:** servo calibration is done and verified with the `kbalance` pose. [`../../blueprints/calibration.md`](../../blueprints/calibration.md)
- **Power:** the robot's own 2-cell pack and the Pi's battery are monitored separately; thresholds and behavior in [`../guides/settings-switches.md`](../guides/settings-switches.md) and [`pi-power.md`](pi-power.md).
