---
audience: contributor
kind: reference
---

# Power

G2 has two batteries: its own pack, which drives the servos and the BiBoard, and a PiSugar S pack, which runs the Pi for about three hours.

Behaviour
---------

- G2's pack: Read through the firmware. G2 warns by voice when the pack is low (7.75 V, about 35% left) and when it is critical (7.4 V). The walk loop reads the voltage under load and rests the legs on a critical reading.
- The Pi's battery: The PiSugar S has no readout. Its warning counts uptime against the measured full-charge runtime and warns at 65% of it (`G2_PI_WARN_FRACTION`). `python -m pi_pipeline.power runtime plugged|unplugged` pauses and restarts the count.
- Sleep: After about 5 minutes at rest, G2 lies down, sighs and sleeps. The wake word or any command wakes G2 with a yawn.
- Shutdown: A short, clear "shut down" lies G2 down, announces it and shuts the Pi down after 6 s. The PiSugar keeps powering the halted Pi, so its switch is flipped by hand.
- Power levers: Three low-risk levers (peripherals off, Wi-Fi power-save, CPU governor) sit behind `python -m pi_pipeline.power status|headless|interactive`.

Interfaces
----------

- Battery reads use the `P` command through the serial link, on demand (at start and before a walk) with a 30 minute backstop (`G2_BATTERY_POLL_S`).
- Sleep and battery watches stand aside while an exploration or goal session runs.

Constraints
-----------

- Sessions start with both packs full, and a block of testing ends when G2's pack passes about 30% at rest or the Pi's low alarm sounds.
- The CPU governor stays `ondemand`, because `powersave` would starve the wake-word listener.
- Hardware sessions with the voice service stopped have no battery watch, so the pack percent is read before each test.

Failure handling
----------------

- Unreadable pack reading: The battery gate warns and continues.
- A reboot clears the runtime count, so the Pi is rebooted after charging.

Verification
------------

- `python -m pi_pipeline.power status` shows the levers, and `python -m pi_pipeline.power runtime list` shows the runtime record.

See [Pi power](../hardware/pi-power.md) and [Operating G2](../guides/operating-g2.md).
