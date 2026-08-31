# Powering the Raspberry Pi — Research Notes

## The problem

Bittle X's BiBoard can power a mounted Raspberry Pi through the same 2×5 GPIO
socket used for serial communication — but Petoi's own documentation confirms a
real tradeoff:

> "Reduced motion capability may happen when connected to Pi! A stronger battery
> is needed." — guide.petoi.com

This matches a well-documented pattern in the general Raspberry Pi / robotics
community: when a Pi shares a battery with servos, the current spikes from servo
movement cause the shared battery's voltage to dip, which can starve the Pi
(weaker movement, or in more severe cases, Pi brownouts / crashes). Multiple
independent Raspberry Pi forum threads confirm this same failure mode outside of
Bittle specifically — the standard community fix is running the Pi off its own
separate power source rather than sharing one with the motors / servos.

**Conclusion:** power the Pi independently rather than relying on Bittle X's
shared battery, especially given RL training / testing involves near-constant
servo movement.

## Choosing a Pi power source

**Considered and ruled out:**

- **Standard phone-style USB power banks** (Vida IT 5000 mAh, VIYISI, FLEXTAIL) —
  electrically fine (5V / 2A+, micro-USB or USB-A output) but physically
  bulky / heavy relative to Bittle X's small frame, and optimized for steady
  phone-charging current rather than the "peaky" current draw a moving robot
  creates.
- **PiSugar S Plus** — looked promising but is explicitly **not** compatible with
  Pi Zero models ("designed for Raspberry Pi 4B, 3B, 3B+ and 2B. Not for Pi
  5 / Zero / Orange Pi" — confirmed on the Amazon listing). Easy to mix up with
  the correctly-matched **PiSugar S** (no "Plus").

**Selected: PiSugar S, 1200 mAh**, correctly matched to Pi Zero W / WH / 2W.

- 5V / 2.5A continuous output
- Connects via spring-loaded pogo pins to bottom copper pads on the Pi's board —
  a different physical contact point than the top-side 40-pin GPIO header,
  confirmed across PiSugar's own docs / GitHub wiki and multiple listings to
  leave the GPIO header itself unoccupied
- Built specifically for robotics / portable-device power delivery (vs. general
  phone charging), with UPS auto-boot / safe-shutdown — useful for recovering
  cleanly from unattended runs

## The GPIO / mounting conflict — resolved

Initial concern: since Bittle X also connects to the Pi via the GPIO header,
would PiSugar and Bittle X's connections physically conflict?

**Resolved: no physical conflict.** PiSugar contacts the Pi's board from the
underside (bottom copper pads), while Bittle X connects via the top-side 40-pin
header pins. They contact opposite faces of the board, so both can be connected
simultaneously.

## The power-sourcing conflict — resolved

Remaining concern: if both PiSugar and Bittle X's board can supply 5V to the Pi at
the same time, does that create an electrical conflict?

**Resolved, with a practical mitigation:** a Pi's 5V GPIO pins are internally one
shared rail, not independent inputs — connecting two same-voltage 5V sources to
that rail doesn't create damage or "backfeed" the way mismatched voltages would
(confirmed via Raspberry Pi community electronics discussion). However, rather
than depending on that being safe for this specific board, the simplest approach
is to **wire Bittle X to the Pi's serial / data pins only (RX / TX / GND) — not
the 5V power pin** — letting PiSugar be the sole power source. This removes the
shared-power question entirely.

## Open item

Confirm with Petoi support (or once hardware is in hand) whether BiBoard V2's
connection to the Pi can be wired data-only, or whether its standard mounting
inherently ties the 5V line together with the data lines by default.

## Sources

- Petoi FAQ — confirms BiBoard can power + communicate with Pi via the 2×5 socket
- Petoi BiBoard V0 Guide — power circuit details
- guide.petoi.com — "Raspberry Pi serial port as an interface" — "reduced motion" / stronger battery note
- Petoi Camp forum — BiBoard power tap thread
- PiSugar official docs / GitHub wiki — GPIO occupation details
- Raspberry Pi Forums — servo/Pi shared-battery brownout threads; GPIO 5V-rail-sharing thread
