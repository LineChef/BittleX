# Powering the Raspberry Pi — Research Notes

## The problem

Bittle X's BiBoard can power a mounted Raspberry Pi through the same 2×5 GPIO
socket used for serial communication — Petoi's own FAQ confirms this is the
stock, default way to run a Pi on Bittle: *"All of our robots run on
NyBoard/BiBoard which can power the Pi and communicate with the Pi through the
serial port in the 2x5 socket."*

**Correction (2026-09-15):** an earlier version of this doc quoted *"Reduced
motion capability may happen when connected to Pi! A stronger battery is
needed"* as if it were general Petoi guidance. Re-traced to its source
(`guide.petoi.com`'s Raspberry-Pi-serial-port page): that warning is on the
**NyBoard/Nybble** section, about Nybble's stock **two 14500 batteries in
series**, and Petoi's own fix for it is to upgrade to *"high drain 7.4 Lipo
batteries, or 2S-18650."* The parallel **BiBoard/Bittle** section of the same
page has **no equivalent warning**. Bittle X's stock battery is already a
7.4 V 2S LiPo (1000 mAh, 2 A typ / 5 A peak, see below) — i.e. already the
"high-drain 7.4 V LiPo" class Petoi tells Nybble owners to upgrade *to*. So
the specific failure mode Petoi documented (weak 14500 cells starving under
Pi + servo load) doesn't obviously carry over to Bittle's stock setup.

What still holds, independent of that misattributed quote: a shared battery's
voltage dips under servo current spikes, which can starve a co-powered
microcontroller (weaker movement, or in more severe cases, Pi brownouts /
crashes) — a board-agnostic pattern confirmed across generic Raspberry Pi
forum threads, not specific to Petoi's hardware. That risk isn't eliminated by
Bittle's bigger battery, just less clear-cut than "Petoi warns against it" —
it's untested on this specific hardware, applied to a workload (RL
training/testing — near-constant servo movement) that's exactly the stress
case where it would show up if it does.

**Conclusion:** power the Pi independently as the cautious choice for this
project's workload, not because there's a confirmed Bittle-specific problem —
sharing BiBoard's battery is a real, commonly-used, simpler option (and avoids
the PiSugar stack-height case-fit question, since a bare Pi already fits
Petoi's stock `Bittle_Cover_with_hole_for_Pi.stl` back cover). PiSugar removes
the open question entirely rather than fixing a confirmed one.

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

## Resolved — data-only wiring confirmed

**2026-09-14:** BiBoard V1's Pi connector is a discrete 5-pin header (TX2,
RX2, GND, +5V, +5V), each pin its own solder pad — not a rigid block that
forces power and data together. Data-only wiring (3 jumpers: TX2/RX2/GND,
both +5V pins left unconnected) is straightforward. Full pinout, confirmed
from Petoi's own official board diagram, plus annotated photos:
[`biboard-pi-connector.md`](biboard-pi-connector.md).

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
| **Disable unused peripherals** (onboard LEDs runtime; audio + camera-LED via boot config) | **BUILT** — `pi_pipeline.power` (`disable_onboard_leds()`, `BOOT_CONFIG_LINES`) | none | boot lines go in `config.txt` at Pi setup (pi-set-up.md) |
| **Wi-Fi power-save when headless** (`iw dev wlan0 set power_save on`) | **BUILT** — `pi_pipeline.power.set_wifi_power_save()` / `apply_headless_profile()` | +100–300 ms per network round-trip. Claude API is already 1–3 s/turn → ~10 % bump, imperceptible in speech. Wake-word is local, unaffected. **Breaks streaming (SSH, live video).** | on in autonomous mode; off when a human is actively connected |
| **idle-REST timeout** — send `d` after N s of no command | yes — behavior/gait, mock-link testable | Must be **behaviour-aware**: laying down during an explore pause (thinking/observing) is slow to resume and looks broken | trigger only from a true "no goals, no stimuli" state; explore mode holds a stand/sit between moves |
| **On-demand vision** — gate the Grove Vision AI V2 | API now; tuned with the camera | **Cannot mean "off during exploration"** — that's how it sees where to go / avoids cliffs. CliffGuard reflex needs a feed whenever it *could* move | "scale to activity": full rate navigating, low rate stationary-monitoring, off only in sleep |
| **Sleep / idle mode** — servos REST, vision off, governor down, Wi-Fi power-save on | logic partly now (`behavior/mode_controller.py`); wake conditions need hardware | Fine *if* wake triggers are good; risk = sleeping through something it should react to | keep a cheap always-on trigger (IMU motion, mic level, wake word); vision + gait stay down until woken. Desirable "rests when nothing's happening" behaviour for a companion bot |
| **CPU governor → `ondemand`** | **BUILT** — `pi_pipeline.power.set_cpu_governor()` (refuses `powersave`) | Ramp latency could cause one late 80 Hz control tick after idle | use `ondemand` (fast ramp), **not** `powersave`; verify with `benchmark_pi.py` loop-jitter |
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

- **DONE:** disable-unused (`pi_pipeline.power`), Wi-Fi power-save toggle,
  CPU-governor helper — `python -m pi_pipeline.power status|headless|interactive`.
- **Focused-session TODO** (needs behaviour-aware design): idle-REST,
  on-demand-vision gate, sleep-mode state machine. idle-REST is the priority.
- **Hardware-gated:** a real power budget from an inline current meter (the
  PiSugar S has no telemetry) — active walking, idle-stand, sit, REST, Pi under
  vision load, Pi asleep. Feeds the sleep-mode timeout tuning.

---

## Sources

- [Petoi FAQ](https://www.petoi.com/pages/faq) — confirms BiBoard can power + communicate with Pi via the 2×5 socket, recommends Pi 3A+/Zero
- Petoi BiBoard V0 Guide — power circuit details
- [guide.petoi.com — "Raspberry Pi serial port as an interface"](https://guide.petoi.com/apis/raspberry-pi-serial-port-as-an-interface) — the "reduced motion" / stronger-battery note is on the **NyBoard/Nybble** section (two 14500 cells); the parallel **BiBoard/Bittle** section has no equivalent warning
- Petoi Camp forum — BiBoard power tap thread
- PiSugar official docs / GitHub wiki — GPIO occupation details
- Raspberry Pi Forums — servo/Pi shared-battery brownout threads; GPIO 5V-rail-sharing thread
