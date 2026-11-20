---
audience: contributor
kind: reference
---

# Serial link

The serial link is the one shared connection between the Pi and the BiBoard, the control board that runs Petoi's OpenCat firmware. Voice, behavior and the gait loop all send commands through it, so serial handling exists once.

Behaviour
---------

- Transport: A serial cable at 115200 baud (`/dev/serial0` on the Pi) carrying short text commands. `kwkF` is walk forward, `ksit` is sit, `d` is lie down and relax, and `gP` and `gp` switch the IMU print on and off.
- Connection: The link opens the port, reconnects after the cable is unplugged without crashing the caller, and builds command strings.
- Eased transitions: Before a firmware skill, the link eases the legs from the known pose to the skill's first frame, capped at 80 degrees per second.
- IMU demultiplexing: With the IMU print on, the board interleaves IMU frames with command replies. Every read path routes IMU lines to a queue instead of handing them back as a reply.
- IMU print stays on: A move of the ball chase (turn, back-up, walk step, claw move, punch) does not switch the print off when it ends, so the stand guard, the stillness wait before a picture and the turn measurement always see frames. A read that needs the board quiet pauses it and puts it back.
- Silence around a behavior skill: A behavior skill (`kpickF`, `kpickD`, `klaunch`, `ktoss`, `khunt`, `kshowOff` and the tricks) is aborted by any byte waiting on the serial port, which the firmware checks before every frame. After sending one the link writes nothing for up to `G2_SKILL_QUIET_S` seconds (10), or until the board echoes `k`: the gyro toggles `gP`, `gp`, `gb` and `gB` wait and go out afterwards in the order they came, the reads `P`, `j` and `?` are dropped, and a motion command goes through at once and ends the wait. Gaits and postures are not behavior skills and are not held.
- Logging: Every command and every board line is written to the command log (`g2cmds`) with who sent it, and a tracing wrapper writes a replayable JSONL file.

Interfaces
----------

- Callers: `send(command, read_reply, settle)` from voice, behavior, the gait loop and the tools. A locked wrapper shares one link between threads.
- Consumers of the IMU: The stand guard, the walk loop and the sensors each read through a fan-out so one reader does not take another's frames.
- Board output: Replies, IMU lines, battery readings and servo feedback rows.

Constraints
-----------

- Never wait inside `send`: The link is shared, and a wait starves the walk loop of IMU frames.
- Refused commands: Calibration, factory pose, the disabled tricks (`khi`, `kscrh`, `kgdb`, `kfiv`, `kjpF`) and the scripted self-right moves are not sent.
- Nothing behind a behavior skill: Never write a byte to the board while a behavior skill plays, from the link or from a tool that opens the port itself; reading is safe. A `gb` written right behind a skill, an IMU print toggle or a joint read cuts the skill off at or before its first frame.
- Beeps: A buzzer beep is deferred to a thread while speech plays, so it never blocks the link.
- One reader of the port: A second process opening the port while the voice service holds it garbles reads, so exploration and goal sessions run inside the service or stop it first.

Failure handling
----------------

- Port down: The link marks itself down, logs the loss and reconnects on the next send.
- Silent board: The caller sees no reply while IMU frames keep arriving. See [Safety and recovery](safety.md).

Verification
------------

- `python -m pi_pipeline.link.check_serial` runs the port, ping and skill checks, and `firstmove` and `allmoves` exercise the joints.
- The firmware tokens are in the [Petoi firmware reference](../hardware/petoi-firmware-reference.md).
