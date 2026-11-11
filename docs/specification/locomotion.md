---
audience: contributor
kind: reference
---

# Locomotion

Locomotion covers how G2 walks, turns, stands up and changes posture. Every motion command goes out through the [serial link](link.md), and the guards that stop or recover motion are in [Safety and recovery](safety.md).

Behaviour
---------

- Default gait: Petoi's scripted forward walk (`kwkF`, played as `wkArmF` with the arm fitted). `G2_DEFAULT_GAIT=policy` selects the learned walk instead.
- Learned walk: A small neural network (ONNX, under 1 MB, with a `.onnx.json` sidecar for its residual scale) adds a bounded correction of at most ±30 degrees per joint to the scripted `wkF` walk. It runs on the Pi at 80 Hz from the IMU and the last joint commands.
- Turns: Line-up and exploration turns use Petoi's `kwkL` and `kwkR`. A turn ends on the gyro once the yaw has changed by the planned angle, never before a minimum run time, and the timed length is the cap.
- Stand-ups: Every stand-up is the eased stand-up, a board-played `K` skill. It starts from rest, a sit, the attention pose or any pose the board reports. The pose is read first (three tries), and an unreadable or unusual pose is laid in rest first.
- Moves into skills: The link eases the legs from the known pose into each firmware skill, so no joint exceeds 80 degrees per second.
- Walk start: After a firmware gait or skill, a walk first settles into a still stand, and it never starts while G2 is tilted past 30 degrees.
- Stopping: A stop out of a stride is `kbalance` and is immediate. A fall lays G2 in the rest position, and no stand-up is sent.

Interfaces
----------

- Input: The IMU stream (roll, pitch, yaw) and the joint commands the loop has sent.
- Output: Text commands to the BiBoard (`k<skill>`, joint commands) through the link.
- Policy file: `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py` names the deployed policy.

Parameters
----------

- `G2_DEFAULT_GAIT`: `firmware` (default) or `policy`
- `G2_STAND_RAMP_S`: The stand-up ramp length (default 0.8 s)
- `G2_TRANSITION_RAMP_S`: The ramp into a firmware skill
- `G2_POSE_BALANCE`: Firmware gyro balance during a pose (on by default; the stand guard switches it off once G2 is still)
- `G2_GYRO_GAITS`: Gyro balance on for scripted gaits only (off by default)

The full list is in [Settings and switches](../guides/settings-switches.md).

Constraints
-----------

- No stand-up other than the eased one: If it cannot run, the command is dropped. The firmware's own quick stand-up is never used.
- Disabled moves: Wave, scratch, shake paw, high five and hop are refused, because they tip G2 over with the pod payload ([Disabled moves](../hardware/disabled-moves.md)).
- Gyro balance: A `gb` is never sent next to a firmware gait, because it stops the walk.
- Per-floor trim: A fixed front-left foot trim per policy is applied, measured on hardwood only.

Failure handling
----------------

- Unreadable pose: Rest first, then the eased stand-up.
- Fall during a walk: The walk loop stops, rests G2 and reports the end reason.
- Late control ticks: The serial send does not wait for the bytes to drain, so a send never stalls the 80 Hz loop.

Verification
------------

- Tests: `pi_pipeline/.venv/bin/pytest` covers the stand-up, transitions and walk loop with no hardware.
- Robot: A 12 s walk on hardwood with a hand near, as in [Gait deployment](../guides/gait-deployment.md), ends with end reason `complete` and no fall.
