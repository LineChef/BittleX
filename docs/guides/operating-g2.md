# Operating G2: safety and day-to-day control

What to know before G2 moves, how to stop him, and how to power things on and off. Commands in full: [`cheatsheet.md`](cheatsheet.md). Lessons from past sessions: [`operating-lessons.md`](operating-lessons.md). A printable two-page version of this page is [`operating-g2-quick-guide.pdf`](operating-g2-quick-guide.pdf).

## Ground rules

- **Never put G2 on his back.** The Pi and the BiBoard are exposed on top. If he falls or is flipped, right him by hand.
- **Every test starts on his feet on the floor with your hands near.** No testing held in the air.
- **Know which floor he is on** and set it before a walking run (`g2floor <label>`); walk logs are labelled by it.
- **Rest or stand G2 before stopping anything that controls him** (`bash tools/g2_safe_stop.sh voice|explore`), never a plain service stop mid-stride.
- **Never deploy new code to the Pi while he is walking, exploring, or being tested.** The deploy script refuses during an exploration or a walk.
- **Never send `Xa` or `XAd` to the BiBoard.** They silently break its onboard voice commands.
- **The AI head can move G2.** It is wired to the BiBoard's serial port (G1), and its model sends commands when you talk to it (press its button, or its wake word "Hi, Jason"). Use it only while G2 is idle or resting, never during a walk or an exploration; after a head session that moved him, power-cycle the BiBoard (or check the IMU stream) before the next walk, because the head can send `g` (the gyro toggle); tell Claude if Pi commands start failing (the wrong-answer horn).

## Stopping G2

| Situation | Do this |
|---|---|
| Anything goes wrong | Say **"emergency stop"** (also "freeze", "halt", "stop moving", "abort"). It latches: all motion is cut and he holds until released. Say **"resume"** (or "as you were", "carry on") to release |
| Voice is not working | `python -m pi_pipeline.app --halt` on the Pi, or `kill -USR1 <pid>` (the pid is in `/tmp/g2_app.pid`). Release with `--release` or `kill -USR2 <pid>` |
| He is moving and nothing is in control | `python -m pi_pipeline.link.check_serial send d` on the Pi (sends rest) |
| An exploration session is running | Say "end exploration mode", or `bash tools/g2_explore.sh stop` (`halt` freezes it, `release` clears the freeze) |
| He fell | The fall guard stops the session and he is rested. Pick him up, check him over, and restart the session; ending the session stops any twitching at rest |

Emergency stop is a freeze, not a power-off. The voice loop listens for it before anything else, with no API call.

## Working on him safely: bench mode

When G2 sits on the calibration stand, or you are running calibration, `check_serial` or an IMU probe, run the app with **`python -m pi_pipeline.app --bench`**. It suppresses autonomous movement and forces the voice actuator to a mock, so nothing else competes for the serial link. For pure diagnostics it is simpler not to run the app at all and use the individual tools, which each open the port themselves.

## Starting and stopping

| | |
|---|---|
| **Power on** | Switch the PiSugar on (the Pi boots and the `g2-voice` service starts the voice loop), and switch the robot's own pack on. Wait for "G2 online" |
| **Normal movement** | Walks use the eased stand-up (0.8 s ramp), and every move into a firmware skill is eased from the pose G2 is known to be in; a stop out of a stride is immediate |
| **Sleep** | After about 5 minutes at rest he lies down and sleeps; say "gee two" to wake him. "Go to sleep" does it on request |
| **Shut down** | Say a short, clear "shut down" (or "power down"): he lies down, announces it, and shuts the Pi down after 6 s (say "cancel" or "wait" to keep it on). **The PiSugar keeps powering the halted Pi, so flip its switch by hand** to cut power. Switch the robot's pack off separately |
| **Lock movement** | Add a systemd drop-in that swaps `--actuator serial` for `--actuator mock` for `g2-voice`, then reload and restart. Details: [`../STATUS.md`](../STATUS.md) |

## Batteries

- The **robot's pack** is read through the firmware; G2 warns by voice when it is low and when it is critical, and the walk loop reads voltage while walking and rests the legs on a critical reading. Thresholds are settings: [`settings-switches.md`](settings-switches.md).
- The **Pi's battery** (PiSugar S) has no readout; its warning counts uptime against the measured full-charge runtime. Run `python -m pi_pipeline.power runtime plugged` on the Pi to pause the count while charging and `runtime unplugged` to restart it; a reboot forgets both. After charging, reboot the Pi. [`../hardware/pi-power.md`](../hardware/pi-power.md)
- Start sessions with both packs full. Stop a block if the robot's pack passes about 30% resting or the Pi's low alarm sounds.

## What to check when something is off

| Symptom | First look |
|---|---|
| No voice reply | `journalctl -u g2-voice -f` on the Pi; then [`operating-lessons.md`](operating-lessons.md) "Voice service and microphone" |
| Walks stop starting | The raw IMU lines: a malformed IMU field once made every line unparseable |
| Board ticks or chirps unexpectedly | The noise log: `python -m pi_pipeline.link.noise_log 60` |
| Servo loud, stiff or hot | Stop the walk and rest him; the servo-heat guard and its logs are in [`../hardware/servo-thermal.md`](../hardware/servo-thermal.md) |
| Anything after the fact | `python -m pi_pipeline.diag summarize` (latest session) and `diag replay SESSION --around HH:MM:SS`: [`../hardware/diagnostics.md`](../hardware/diagnostics.md) |
| First power-on, new hardware | `python -m pi_pipeline.doctor [--serial]` and the guided `python -m pi_pipeline.bringup`: [`bring-up-sequence.md`](bring-up-sequence.md) |
