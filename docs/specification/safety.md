---
audience: contributor
kind: reference
---

# Safety and recovery

This page specifies how G2 is stopped, how falls and failures are detected, and which commands are never sent. The operating rules for people are in [Operating G2](../guides/operating-g2.md).

Behaviour
---------

- Emergency stop: "Emergency stop", "freeze", "halt", "stop moving" and "abort" latch a stop that cuts all motion. "Resume" releases it. The voice loop checks for it before anything else, with no API call. `python -m pi_pipeline.app --halt` and `kill -USR1 <pid>` do the same, and `--release` or `kill -USR2` release it.
- Fall guard: A tilt past the fall limit (60 degrees for 0.3 s) stops the session and lays G2 in the rest position. A fall is never answered with a stand-up.
- Stand guard: While G2 is idle, firmware gyro balance is kept off. A wobble detector reads the 5 Hz IMU stream and switches balance off if a limit cycle starts.
- Sag recovery: Legs that have let go tilt the body away from how it stood. After 5 s without a command, a tilt of more than 10 degrees from the stand reference, or more than 20 degrees from level, runs the recovery: the attention pose, then the eased stand-up back legs first. During a roam, a median tilt that moves 12 degrees from the walk's own reference holds the walker and runs the same recovery.
- Battery gates: A hardware session reads the pack percent before each test, and a motion gate refuses below the configured percent (30% in the hardware tests). The walk loop reads the voltage under load and rests the legs on a critical reading.
- Thermal guard: A servo heat estimate backs off a walk before a servo overheats.
- Jam guard: A strain-based reflex stops a walk that is pushing against something.

Interfaces
----------

- Inputs: The IMU stream, the pack voltage, the voice command log and the halt signals.
- Outputs: Rest (`d`, `krest`), the eased stand-up, and spoken or sounded alerts (the wrong-answer horn marks a refused command).

Constraints
-----------

- Refused commands: Calibration and factory-pose commands, and `Xa` and `XAd`, are never sent. The serial link refuses them.
- Back: G2 is never put on his back, because the Pi and BiBoard are exposed on top.
- Deploys: New code is never deployed while G2 walks, explores or is tested.

Failure handling
----------------

- BiBoard silent: If the board streams IMU data but ignores commands, the Pi-to-BiBoard plug is checked first, because it comes undone in falls. Power-cycling the BiBoard clears it.
- Board-started moves: A move the BiBoard's own voice module starts is flagged `not_from_pi` in the command log (`g2cmds`).
- Stalled loop: A watchdog beats once per control tick and triggers a safe stop when the beat stops.

Verification
------------

- Tests cover the guards with synthetic IMU streams and a fake link.
- Robot: Saying "emergency stop" during a walk stops all motion, and "resume" releases it.
