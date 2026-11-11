---
audience: builder
kind: guide
---

# Operating G2: safety and day-to-day control

This page specifies the constraints that apply whenever G2 moves, the ways to stop G2, and the power-on, sleep and shutdown behaviour. Commands are listed in the [cheat sheet](cheatsheet.md), operating constraints found in use are in [Operating notes](operating-lessons.md), and a printable two-page version of this page is [the quick guide](operating-g2-quick-guide.pdf).

## Operating constraints

- **Orientation.** G2 is never placed on his back. The Pi and the BiBoard are mounted on top and exposed. A fallen or flipped G2 is righted by hand.
- **Test start.** Every test starts with G2 standing on the floor and a hand within reach. No test runs with G2 held in the air.
- **Floor label.** The floor type is set before a walking run with `g2floor <label>`. Each walk log records it.
- **Stopping services.** Anything that controls G2 is stopped with `bash tools/g2_safe_stop.sh voice|explore`, which rests or stands G2 first. A plain service stop during a stride is not supported.
- **Deployment.** New code is deployed to the Pi only while G2 is idle. The deploy script refuses during an exploration or a walk.
- **Voice module commands.** `Xa` and `XAd` are never sent to the BiBoard, because they disable its onboard voice commands without any visible error.
- **AI head.** The head shares the BiBoard's serial port (G1) and issues commands when spoken to, by its button or its wake word "Hi, Jason". It is used only while G2 is idle or resting, never during a walk or an exploration. After a head session that moved G2, the BiBoard is power-cycled or the IMU stream is checked before the next walk, because the head can send `g` (the gyro toggle). Pi commands that start failing (the wrong-answer horn) indicate this state.

## Stopping G2

- **Any fault**: Say **"emergency stop"** (also "freeze", "halt", "stop moving", "abort"). The stop latches: all motion is cut and G2 holds until released. Say **"resume"** (also "as you were", "carry on") to release.
- **Voice unavailable**: Run `python -m pi_pipeline.app --halt` on the Pi, or `kill -USR1 <pid>` (the pid is in `/tmp/g2_app.pid`). Release with `--release` or `kill -USR2 <pid>`.
- **Moving with nothing in control**: Run `python -m pi_pipeline.link.check_serial send d` on the Pi, which sends rest.
- **During an exploration**: Say "end exploration mode", or run `bash tools/g2_explore.sh stop`. `halt` freezes the session and `release` clears the freeze.
- **After a fall**: The fall guard stops the session and rests G2. Pick G2 up, inspect, and restart the session. Ending the session stops any twitching at rest.

Emergency stop is a freeze, not a power-off. The voice loop checks for it before anything else, with no API call.

## Bench mode

With G2 on the calibration stand, or while calibration, `check_serial` or an IMU probe is running, the app runs as `python -m pi_pipeline.app --bench`. Bench mode suppresses autonomous movement and replaces the voice actuator with a mock, so nothing else competes for the serial link. For pure diagnostics, the individual tools can be run without the app, because each opens the serial port itself.

## Power, sleep and shutdown

- **Power on**: Switch the PiSugar on, which boots the Pi and starts the `g2-voice` service, then switch G2's own pack on. G2 says "G2 online" when ready.
- **Movement**: Every stand-up is the eased stand-up (a 0.8 s ramp). Every move into a firmware skill is eased from the known pose. A stop out of a stride is immediate.
- **Sleep**: After about 5 minutes at rest, G2 lies down and sleeps. Saying "gee two" wakes G2, and "go to sleep" sleeps G2 on request.
- **Shut down**: Say a short, clear "shut down" or "power down". G2 lies down, announces it, and shuts the Pi down after 6 s. Saying "cancel" or "wait" keeps the Pi on. The PiSugar keeps powering the halted Pi, so its switch is flipped by hand. G2's pack is switched off separately.
- **Locked movement**: A systemd drop-in that replaces `--actuator serial` with `--actuator mock` for `g2-voice`, followed by a reload and restart, disables all movement.

## Batteries

- **G2's pack** is read through the firmware. G2 warns by voice when it is low and when it is critical. The walk loop reads the voltage under load and rests the legs on a critical reading. The thresholds are settings, listed in [Settings and switches](settings-switches.md).
- **The Pi's battery** (PiSugar S) has no readout. Its warning counts uptime against the measured full-charge runtime. `python -m pi_pipeline.power runtime plugged` pauses the count while charging and `runtime unplugged` restarts it. A reboot clears both, so the Pi is rebooted after charging. See [Pi power](../hardware/pi-power.md).
- **Session start**: Sessions start with both packs full. A block of testing ends when G2's pack passes about 30% at rest or the Pi's low alarm sounds.

## Diagnosing a fault

- **No voice reply**: Run `journalctl -u g2-voice -f` on the Pi, then see "Voice service and microphone" in [Operating notes](operating-lessons.md).
- **Walks stop starting**: Read the raw IMU lines. A malformed IMU field makes every line unparseable.
- **Unexpected ticks or chirps from the board**: Run `python -m pi_pipeline.link.noise_log 60` to read the noise log.
- **Loud, stiff or hot servo**: Stop the walk and rest G2. The servo-heat guard and its logs are described in [Servo thermal](../hardware/servo-thermal.md).
- **After the fact**: `python -m pi_pipeline.diag summarize` reports the latest session, and `diag replay SESSION --around HH:MM:SS` replays a moment. See [Diagnostics](../hardware/diagnostics.md).
- **First power-on of new hardware**: Run `python -m pi_pipeline.doctor [--serial]` and the guided `python -m pi_pipeline.bringup`. See [Bring-up sequence](bring-up-sequence.md).
