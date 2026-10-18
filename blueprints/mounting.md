# Mounting and case: as built

How the Pi, the PiSugar S battery, the camera, the speaker and the microphone are attached to G2's frame. Since 2026-10-17 G2 carries the **Bittle X Pi add-on** (v0.24) on the **Bittle X Platform** (v3.2), a case designed for this project's parts. The design, the print files and the full build guide are in the separate project: [Bittle X Platform and Pi add-on](https://beetlebugorg.github.io/bittlex/) (3D viewer: [`/viewer/`](https://beetlebugorg.github.io/bittlex/viewer/)). This page records what G2 uses and where things sit; the project holds the step-by-step assembly, so it is not copied here. Wiring is in [`wiring/g2-wiring-guide.html`](wiring/g2-wiring-guide.html); the parts and their weights in [`../docs/hardware/as-built.md`](../docs/hardware/as-built.md).

## What is on G2 now

Front is the head end; left and right are G2's left and right.

| Part | Where and how it is attached |
|---|---|
| Platform cover | The stock Petoi back cover, replaced by the platform cover (`cover_pegs_foot.stl`, the Petoi cover with four teardrop pegs on top). The Pi slot and the BiBoard header are at the front left |
| Pod (body + top panel) | Clicks onto the four pegs: set it 7 mm behind its place with the grille to the rear, slide it 7 mm forward until it clicks (about 3.2 N). No tools, glue or tape. To remove: open the panel, pull the three BiBoard plugs off, slide the body 7 mm rearward and lift |
| Pi Zero 2 W + PiSugar S | In the pod, held in the grooves of the two end posts: ports up, 40-pin header down and toward the left wall, SD card at the rear. The Pi plugs and the BiBoard header are in the left well. The PiSugar switch is under a window in the panel beside the HDMI opening (move it with a fingernail) |
| Camera | **On top of the pod, front of the panel**, in a printed camera mount (a bayonet socket in the panel: turn 40° counterclockwise, drop in, turn 40° clockwise to click). The camera case snaps between the mount's brackets with the **lens forward and the USB port up**. The mount can be turned end for end to point the lens to the rear. USB cable (USB-C at the camera, micro-USB at the Pi's data port) runs about 120 mm |
| Speaker | **At the rear of the pod**, wings in the side grooves, body toward the rear grille. Its 2-pin lead goes to the rear end of the amp |
| Amplifier (NS4168) | On the **right wall**, bottom edge in a slot, top edge under two nubs, set with a dab of glue |
| Microphone (SPH0645) | On the **right wall near the front**, in slots in a post and a ledge; the port faces the wall, the header is at the front edge. A fork under the panel holds its top edge |
| BiBoard link | Three jumpers (TX2, RX2, GND) from the Pi header to BiBoard's 5-pin socket; the two +5V sockets stay empty (the Pi has its own power). Wire detail: [`build-logs/pi-biboard-build-notes.md`](../docs/hardware/build-logs/pi-biboard-build-notes.md) |

What changed from the interim mount (2026-09-29 to 2026-10-17): the camera moved from the front of the case to the top of the pod, the speaker stays at the very back, and the microphone moved from the top of the lid to the right wall near the front. The payload is now inside one pod instead of PiSugar's own case velcroed to a modified cover. The pod is designed for the **PiSugar S**. The project's site, guide and 3D viewer say "PiSugar 2" throughout; that is an error in their documentation (confirmed by the owner, who is the case's designer), so read every "PiSugar 2" there as the PiSugar S.

**Mass:** the design's own figure is **135 g with the electronics** (center of mass 9.0 mm from the robot center). **G2's weighed payload (Pi, PiSugar S, camera, speaker, microphone, wiring and the pod) is 185 g** (2026-10-17), against 168 g with the previous mount: 17 g (about 10%) more. G2 now also carries the **Petoi AI Head** (42 g, Petoi's figure; it replaces the stock head on the head servo, [`../docs/planned/ai-head/README.md`](../docs/planned/ai-head/README.md)), counted on top of the 185 g: payload **227 g**, about 50% of Petoi's recommended 1 lb (453.6 g) maximum carry (owner's recollection, not yet sourced). With the base robot unchanged at about 254 g, the whole robot is about **481 g** (was 422 g). The sim uses these numbers ([`../docs/hardware/specs.md`](../docs/hardware/specs.md)).

## Wiring in the pod

G2's own wiring guide ([`wiring/g2-wiring-guide.html`](wiring/g2-wiring-guide.html), [I²S build log](../docs/hardware/build-logs/i2s-audio-build-log.md)) is the source of truth for the pins and is not changed by the pod. The project's build guide shows the same pins except the amp ground on pin 14 (G2's is on pin 9); the table below is the project's, for comparison.

| Signal | Pi pin |
|---|---|
| Mic 3V / mic GND | 1 / 9 |
| Amp V (5 V) / amp G | 2 / 14 |
| BiBoard GND / RX2 / TX2 | 6 / 8 / 10 (TX and RX cross) |
| BCLK (mic and amp, one splice) | 12 |
| LRCLK (mic and amp, one splice) | 35 |
| Mic DOUT / mic SEL | 38 / 39 |
| Amp DIN | 40 |

The mic's SEL is on pin 39 (a ground, left channel), as before. All wire lengths and the route of every wire are in the project's build guide ("Wire table").

## Measurements that any mount has to respect

- Platform interface: four pegs at (X, Z) = (±12, −5.5) and (±12, 14.5) mm, a centred 24 × 20 mm rectangle; add-on plate bottom at 26 mm above the cover origin, 1.5 mm thick at the keyholes; slide 7 mm. Frame: +X robot right, +Z toward the tail (−Z is the head end).
- The pod must stay within Z −37.8 to 56.2 mm and |X| ≤ 29.6 mm (beyond that, check the legs and the head). The head turns −85° to 85° without contact (the project's model check).
- Keep the add-on's center of mass within 10 mm of Z 0. Heavy parts low and near the pegs.
- Keep the BiBoard header (X −27.27 to −24.73, Z −25.1 to −12.4) and the Grove plug space (the head camera cable, front-left notch) clear.
- Pi Zero 2 W and PiSugar S are both 65 × 30 mm. The Pi needs its own power: wiring 5 V from BiBoard as well would put two 5 V sources on the Pi. The link is data only.
- Printing (all parts, no supports): PLA works; PETG for parts that are removed often or get warm. 0.20 mm layers (first layer 0.25 mm), 3 walls, 20% gyroid, 220 °C (the project's "Bittle X" Cura profile). The platform cover prints standing on its rear end with a break-off foot (`cover_pegs_foot`).

## Back touch sensor

On a Bittle X V2 the back touch sensor is a flexible circuit glued inside the cover top; the add-on covers most of its touch areas, and the project advises disabling back-touch mode (serial command `Xb`) while an add-on is on the robot. G2's touch sensors are not enabled, so nothing needs to be done. Do not send `Xa` or `XAd` to the BiBoard voice module (see the project rules).

## Open items

- [ ] The front/rear weight split with the pod and the AI head, and a weighing of the whole robot with both (the sim says about 51% on the front paws and 480 g; the AI head's size, position and mass inside the sim are estimates, and its mass is added in full although the stock head it replaces is part of the 254 g base).
- [ ] The camera's real field of view from its new position and height. Its orientation is unchanged from the old mount.
- [ ] Mic gain and speaker loudness in the new positions (the mic moved to the wall, the speaker faces a rear grille).

## Licenses

Per the project: code MIT; designs and documents CC BY 4.0 (Jeremy Collins); the Petoi cover, side shoulder and front plate models come from [PetoiCamp/NonCodeFiles](https://github.com/PetoiCamp/NonCodeFiles), published without a stated license, and `cover_pegs.stl` is made from the Petoi cover; the PiSugar fit models are GPL-3.0. This repository links to the project and does not copy its files.

## History

The first mounting research (a corner-clip design, measurements, and why it was abandoned) is in [`../docs/archive/mounting-research-2026-09.md`](../docs/archive/mounting-research-2026-09.md). The interim mount used PiSugar's own case shell (75 × 31 × 36 mm, nearly twice the stock cover's 18.6 mm internal depth) velcroed on top of a modified Petoi cover (`Bittle_Cover_with_hole_for_Pi.stl`, with the PiSugar switch exposed and the SD port widened), with the camera at the front of the case, the speaker at the very back and the microphone on top of the lid (all confirmed 2026-09-29 to 2026-10-06; payload about 168 g, roughly 100 × 40 × 38 mm).
