# Wiring PiSugar, the Pi, and BiBoard together

How G2's three electronics pieces connect: PiSugar (Pi power), the Raspberry
Pi Zero 2 W (voice/vision/memory), and BiBoard (walking/servos).

```
PiSugar S  --2 pogo pins (5V+GND), 4 screws, no wiring-->  Pi Zero 2 W  --3 wires (TX/RX/GND)-->  BiBoard V1
```

## What you'll need

- [ ] Raspberry Pi Zero 2 **WH** (header pre-soldered)
- [ ] PiSugar S, with its 4 mounting screws (included in the PiSugar box)
- [ ] BiBoard V1 — check whether Petoi included a ready-made BiBoard&harr;Pi
      cable in the Bittle X box before doing anything below; if so, skip to
      Step 3
- [ ] A 5-pin header to solder onto BiBoard, if one isn't already there
- [ ] Female-to-female Dupont jumper wires (3 needed; a 40-pack is cheap and
      the rest are reusable elsewhere)
- [ ] Soldering iron + solder, only if BiBoard's header isn't already
      populated
- [ ] A 3D-printed Pi standoff to mount the assembly to the frame — Petoi's
      official part, [`Pi_StandOffRegular.stl`](https://github.com/PetoiCamp/NonCodeFiles/raw/master/stl/Bittle%20%26%20BittleX/RaspberryPiStandOff/Pi_StandOffRegular.stl)
      (see "Mounting the Pi assembly" below)

## Step 1 — Mount PiSugar to the Pi

![PiSugar S board, top view](images/biboard-pi-connector/pisugar-s.png)

Align PiSugar's 4 screw holes underneath the Pi and secure it with the
included screws. Two spring-loaded pogo pins on PiSugar make contact with two
pads on the underside of the Pi automatically — **5V and GND, power only**.

No wiring, no soldering, no pin diagram to check — the screw holes only line
up one way.

## Step 2 — Prepare BiBoard's Pi header

The connector is a 5-pin header at BiBoard's top edge, just above the servo
connectors (G1&ndash;G4):

![BiBoard V1 front, with the 5-pin Raspberry Pi header outlined near the top edge](images/biboard-pi-connector/board-overview.png)

If it isn't already populated, solder a 5-pin header there. Left to right:

| Pin | Label |
|---|---|
| 1 (square pad) | TX2 |
| 2 | RX2 |
| 3 | GND |
| 4 | +5V |
| 5 | +5V |

## Step 3 — Wire the Pi to BiBoard

Three wires, crossed — one board's "sending" line goes to the other's
"listening" line:

| From (BiBoard) | To (Pi) |
|---|---|
| TX2 | pin 10 (GPIO15, RXD) |
| RX2 | pin 8 (GPIO14, TXD) |
| GND | pin 6 |

Leave BiBoard's two +5V pins and the Pi's pin 2 (5V) **unconnected** — PiSugar
is already powering the Pi.

BiBoard side, zoomed &mdash; the three pins to wire are checked, the two +5V
pins are marked to skip:

![Close-up of BiBoard's 5-pin header: TX2, RX2, GND checked; both +5V pins marked with an X](images/biboard-pi-connector/header-detail.png)

Pi side, the other end of the same 3 wires &mdash; the relevant pins are the
first 5 columns of the header, nearest the microSD slot. Pin 1 (square,
top-left) orients you:

![Raspberry Pi Zero 2 W, with the GPIO header outlined near the top edge](images/biboard-pi-connector/pizero-overview.png)

![Close-up of the Pi's header: pin 1 marked with a white square, pin 2 (5V) marked to skip, pins 6/8/10 checked for GND/TXD/RXD](images/biboard-pi-connector/pizero-detail.png)

(The photo above shows a bare Pi Zero 2 W with unpopulated pads — your WH kit
ships with the header already soldered, so there's nothing to solder on the
Pi side, only on BiBoard's, in Step 2.)

## Step 4 — Before powering on

- [ ] Both of BiBoard's +5V pins are empty — no wire on either
- [ ] The Pi's pin 2 (5V) is empty
- [ ] BiBoard TX2 goes to Pi **pin 10**, not pin 8 (they're easy to swap)
- [ ] All 3 wires are seated firmly at both ends

## Mounting the Pi assembly (standoff, not stacking on BiBoard)

Petoi's own FAQ and accessory library confirm how the Pi physically attaches
to Bittle/Bittle X — this is not guessed:

- Petoi's FAQ: *"Both Nybble/Nybble Q and Bittle/Bittle X support connecting
  to a Raspberry Pi directly... You may need to 3D print extra support
  structures for your project. Here's the 3D-printed Pi-support for
  Bittle."* ([petoi.com/pages/faq](https://www.petoi.com/pages/faq))
- That support is a real, published part: **`Bittle_standoffPi.stl`**, in
  Petoi's official accessories repo, folder
  [`stl/Bittle & BittleX/RaspberryPiStandOff/`](https://github.com/PetoiCamp/NonCodeFiles/tree/master/stl/Bittle%20%26%20BittleX/RaspberryPiStandOff) —
  containing `Pi_StandOffRegular.stl` (this build's target — Pi Zero 2 W),
  `Pi3A_standOff.stl` (for the Pi 3A+), and a `.3mf` of the same part.
- A standoff is a spacer post: it screws to the robot's frame and elevates
  the Pi (with PiSugar screwed underneath it) above whatever is below it. The
  Pi assembly is **not resting on BiBoard's PCB** — both BiBoard and the
  standoff mount to the frame independently. The only thing that connects the
  Pi to BiBoard at all is the 3-wire TX/RX/GND link from Step 3 — there is no
  mechanical connection between the two boards.
- Standoff height and exact mounting-hole positions aren't published
  anywhere found, so the clearance and footprint alignment shown below are
  the most defensible reading of the confirmed facts, not a measurement.

## What it should look like assembled

No real photo exists yet — these are illustrative diagrams (not real photos),
drawn to real relative scale. The stacking order and sizes are derived from
the sources above and from the real dimensions below; the exact footprint
alignment is a best guess, reasoned as follows:

- PiSugar's own documentation confirms it mounts **under** the Pi and contacts
  two dedicated pads, never the GPIO header — so the header stays free on top,
  the Pi doesn't need to be flipped.
- **Pi Zero 2 W and PiSugar S are both a confirmed 65 × 30 mm** — identical
  footprints, which is why they're drawn as one overlaid shape below.
  **BiBoard measures ~68 × 59 mm**, estimated from its photo using the USB-C
  connector's standardized shell width (~8.7 mm) as a scale reference — Petoi
  doesn't publish an official spec. BiBoard is close in width to the Pi/PiSugar
  footprint but nearly double the depth.
- Because the Pi↔BiBoard link is loose wires, not a rigid pin-header stack,
  nothing forces the Pi's footprint to align with BiBoard's header position —
  the wires can route however they need to. Since BiBoard's real footprint is
  bigger than the Pi+PiSugar's in both directions, the diagrams below **nest**
  the smaller Pi/PiSugar footprint inside BiBoard's larger one (with margin on
  every side), rather than showing an unmotivated overhang past BiBoard's
  edge — an earlier draft of this diagram assumed pin-driven alignment and
  drew the Pi hanging off BiBoard's edge; that assumption didn't hold up once
  the wire-vs-rigid-header distinction was worked through.

Top-down, all three genuinely overlapping at their real position and size —
semi-transparent fills so the overlap itself is visible, the Pi/PiSugar
footprint nested inside BiBoard's larger one with margin on every side, plus
the standoff's two mounting posts (approximate position — exact hole spacing
isn't published):

![Illustrative top-down diagram: BiBoard, PiSugar, and the Pi drawn at their real relative sizes, the smaller Pi/PiSugar footprint nested inside BiBoard's larger one, with the standoff's two mounting posts marked](images/biboard-pi-connector/assembled-topdown.png)

Side view of the same stack, each layer solid, with the printed standoff
holding the Pi assembly clear of BiBoard and both mounted to a shared frame:

![Illustrative side-view diagram: BiBoard mounted to the frame, a printed standoff rising from the same frame to hold PiSugar and the Pi above it, wires routed from the Pi's header down past the standoff to BiBoard's header](images/biboard-pi-connector/assembled-side.png)

## Reference

Full pinout, both boards:

| | BiBoard | Pi |
|---|---|---|
| Ground | GND | pin 6 |
| BiBoard sends / Pi receives | TX2 | pin 10 (RXD) |
| Pi sends / BiBoard receives | RX2 | pin 8 (TXD) |
| Power (not wired) | +5V, +5V | pin 2 |

An interactive version of the diagrams above — the Pi's full 40-pin header,
the PiSugar/Pi/BiBoard overview, and a combined view with the wires drawn
crossing between the two boards — is published at
[G2 Electronics Wiring](https://claude.ai/artifact/TBtEVxXmmQ97mHRgXyiuMq).

Source diagram (both sides of BiBoard, all 17 numbered components):
[`petoi-official-diagram.png`](images/biboard-pi-connector/petoi-official-diagram.png).

**Note:** BiBoard V1's spec sheet lists Pi compatibility as "Pi 3A+, 4, 5" —
the Pi Zero 2 WH isn't named. The pins used here (5V/GND/GPIO14/GPIO15) are
identical across every 40-pin Pi header including the Zero 2 W, so this is
expected to work regardless — worth a quick visual check of the header once
both boards are in hand.

### Sources

- [For BiBoard V1 | Petoi Doc Center](https://docs.petoi.com/apis/raspberry-pi-serial-port-as-an-interfac/for-biboard-v1)
- [BiBoard V1 Guide | Petoi Doc Center](https://docs.petoi.com/biboard/biboard-v1-guide) — source of the official board diagram
- [PiSugarS Series | PiSugar Docs](https://docs.pisugar.com/docs/product-wiki/battery/pisugar-s-series)
- [PiSugar S | Tindie](https://www.tindie.com/products/pisugar/pisugar-s-battery-for-raspberry-pi-zero/) — "bottom connection... without affecting GPIO expansion," confirming PiSugar mounts under the Pi and never touches the GPIO header
- [Raspberry PI Zero 2W TOP 02.jpg | Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Raspberry_PI_Zero_2W_TOP_02.jpg) — CC BY-SA 4.0, source of the Pi Zero 2 W photos above
- BiBoard's ~68 × 59 mm size is not published anywhere found — measured from `petoi-official-diagram.png` using the on-board USB-C receptacle's standardized shell width (~8.7 mm) as a pixel-to-mm scale reference
- [Frequently Asked Questions | Petoi](https://www.petoi.com/pages/faq) — confirms direct Pi mounting on Bittle/Bittle X and links the official Pi standoff accessory
- [`RaspberryPiStandOff/` | PetoiCamp/NonCodeFiles on GitHub](https://github.com/PetoiCamp/NonCodeFiles/tree/master/stl/Bittle%20%26%20BittleX/RaspberryPiStandOff) — the official 3D-printable Pi standoff: [`Pi_StandOffRegular.stl`](https://github.com/PetoiCamp/NonCodeFiles/raw/master/stl/Bittle%20%26%20BittleX/RaspberryPiStandOff/Pi_StandOffRegular.stl) (Pi Zero 2 W / this build), [`Pi3A_standOff.stl`](https://github.com/PetoiCamp/NonCodeFiles/raw/master/stl/Bittle%20%26%20BittleX/RaspberryPiStandOff/Pi3A_standOff.stl) (Pi 3A+)
