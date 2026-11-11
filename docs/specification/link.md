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
