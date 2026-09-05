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

---

# Power-management measures — maximizing runtime

Drafted 2026-09-05. Two independent budgets:

- **Robot 2S pack (7.4 V, 1000 mAh, 2 A typ / 5 A peak)** — leg servos + BiBoard.
  Caps *walking time* (~45–60 min active). Relaxed servos draw ≈ 0; any held
  pose draws continuous holding current.
- **PiSugar S (1200 mAh)** — Pi Zero 2 W + camera + audio. Runs whether or not
  the robot moves; caps *awake time*. No battery telemetry on the S.

Guiding principle: **these are IDLE-STATE optimizations.** Active autonomous
operation (exploring, navigating, reacting) is a *working* state — you can't
save power there by gating what autonomy depends on. During active autonomy the
only levers are the clean set (efficient gait, disabled peripherals).

## Rest pose (servo pack)

Power, lowest → highest: **REST (`d`) < sit (`ksit`) < stand (`kup`)**.
- **REST** — legs folded, body on the frame, servos de-energized, ≈ 0 draw.
- **sit** — partial; some servos still hold. Middle option if it must stay
  "ready".
- **stand** — all 8 leg servos fighting gravity at a poor mechanical angle;
  highest continuous draw.

Resume cost: REST → walking is ~1–2 s + a rebalance; stand → walking is instant.
So **fold to REST only when idle > a few seconds**, not for a 1 s gap.

## Measures

| Measure | Buildable now? | Autonomy impact | Rule |
|---|---|---|---|
| **Disable unused peripherals** (onboard LEDs, audio-out; BT already off for the serial port; Zero 2 has no HDMI) | yes — Pi-setup `config.txt` + systemd | none | just do it |
| **Wi-Fi power-save when headless** (`iw dev wlan0 set power_save on`) | yes — helper keyed to mode | +100–300 ms per network round-trip. Claude API is already 1–3 s/turn → ~10 % bump, imperceptible in speech. Wake-word is local, unaffected. **Breaks streaming (SSH, live video).** | on in autonomous mode; off when a human is actively connected |
| **idle-REST timeout** — send `d` after N s of no command | yes — behavior/gait, mock-link testable | Must be **behaviour-aware**: laying down during an explore pause (thinking/observing) is slow to resume and looks broken | trigger only from a true "no goals, no stimuli" state; explore mode holds a stand/sit between moves |
| **On-demand vision** — gate the Grove Vision AI V2 | API now; tuned with the camera | **Cannot mean "off during exploration"** — that's how it sees where to go / avoids cliffs. CliffGuard reflex needs a feed whenever it *could* move | "scale to activity": full rate navigating, low rate stationary-monitoring, off only in sleep |
| **Sleep / idle mode** — servos REST, vision off, governor down, Wi-Fi power-save on | logic partly now (`behavior/mode_controller.py`); wake conditions need hardware | Fine *if* wake triggers are good; risk = sleeping through something it should react to | keep a cheap always-on trigger (IMU motion, mic level, wake word); vision + gait stay down until woken. Desirable "rests when nothing's happening" behaviour for a companion bot |
| **CPU governor → `ondemand`** | yes — one-liner at setup | Ramp latency could cause one late 80 Hz control tick after idle | use `ondemand` (fast ramp), **not** `powersave`; verify with `benchmark_pi.py` loop-jitter |
| **Camera resolution / fps down** | with hardware | detection may degrade | drop only if detection still passes |
| **PiSugar low-power mode** | with hardware | — | check if it exists and whether the Pi can trigger it |

## NOT "no performance impact" — real tradeoffs (flagged, not recommended as free)

- Weighting `FAC_POWER` harder in training — trades agility/speed for current.
- Lower control rate (80 → 50 Hz) — robustness risk.
- Slower cruise — cost-of-transport curve means *very* slow can be less
  efficient per metre; `TARGET_SPEED` 0.10 m/s is already near the efficient
  point.
- Battery-aware slowdown at low voltage — deliberately sacrifices performance
  to extend runtime.

## Next

- **Implement now:** disable-unused list, Wi-Fi power-save toggle, CPU-governor
  script, behaviour-aware idle-REST, on-demand-vision gate API, sleep-mode state
  machine skeleton.
- **Hardware-gated:** a real power budget from an inline current meter (the
  PiSugar S has no telemetry) — active walking, idle-stand, sit, REST, Pi under
  vision load, Pi asleep. Feeds the sleep-mode timeout tuning.

---

## Sources

- Petoi FAQ — confirms BiBoard can power + communicate with Pi via the 2×5 socket
- Petoi BiBoard V0 Guide — power circuit details
- guide.petoi.com — "Raspberry Pi serial port as an interface" — "reduced motion" / stronger battery note
- Petoi Camp forum — BiBoard power tap thread
- PiSugar official docs / GitHub wiki — GPIO occupation details
- Raspberry Pi Forums — servo/Pi shared-battery brownout threads; GPIO 5V-rail-sharing thread
