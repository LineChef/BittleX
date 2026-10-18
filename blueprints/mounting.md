# Mounting and case: as built

How the Pi, the PiSugar battery, the camera, the speaker and the microphone are attached to G2's frame. **The current mount is interim, and this page is still being completed**: the sections marked *To be recorded* are blanks for the builder to fill in with the real details and photos. Wiring is in [`wiring/g2-wiring-guide.html`](wiring/g2-wiring-guide.html); the parts and their weights in [`../docs/hardware/as-built.md`](../docs/hardware/as-built.md).

## What is on G2 now

| Part | How it is attached | Confirmed |
|---|---|---|
| Pi Zero 2 W + PiSugar S | Screwed together, then inside PiSugar's own official case (shell for the 1200 mAh model, common cap, pin cap). The case is **velcroed to the outside** of the modified back cover | 2026-09-29 |
| Back cover | Petoi's stock cover with a Pi cutout (`Bittle_Cover_with_hole_for_Pi.stl`), modified to expose the PiSugar's switch and widen the SD-card port | 2026-09-29 |
| Camera | Front of the case | 2026-10-06 |
| Speaker | Very back of the case | 2026-10-06 |
| Microphone | Top of the lid | 2026-10-06 |
| BiBoard link | Three jumper wires (TX, RX, GND) from the Pi header to BiBoard's 5-pin socket; the Pi has its own power | [`build-logs/pi-biboard-build-notes.md`](../docs/hardware/build-logs/pi-biboard-build-notes.md) |

Why the case sits outside the cover: PiSugar's case shell measures 75.00 × 31.00 × 36.00 mm, and its 31 mm dimension is nearly twice the stock cover's 18.6 mm internal depth, so it cannot be enclosed inside it. Velcro avoids the conflict instead of solving it, and the payload (Pi, PiSugar, camera, speaker, mic, wiring and lid) is about 168 g, roughly 100 × 40 × 38 mm, centred on the spine. Balance and weights: [`../docs/hardware/specs.md`](../docs/hardware/specs.md) "Weight distribution, standing".

## Measurements that any mount has to respect

- Pi Zero 2 W and PiSugar S are both 65 × 30 mm. Assembled, from the bottom of the PiSugar to the top of the Pi's bare PCB (header excluded): about 19.05 mm.
- BiBoard is about 68 × 59 mm (estimated from a photo; Petoi publishes no spec).
- The PiSugar's power switch lands under the Pi's mini-HDMI edge once oriented correctly; a cover or mount should keep it reachable.
- No corner of the Pi's top side is free of components, so a corner-grip clip cannot work; the four mounting holes are already used to screw the PiSugar to the Pi.
- The Pi needs its own power: wiring 5 V from BiBoard as well would put two 5 V sources on the Pi. The link is data only.

## To be recorded

These are the blanks to fill in; nothing is guessed here.

- [ ] The printed parts: which files, material, print settings, and where each file came from.
- [ ] Exactly how the camera is fixed to the case and which way it faces (the module is mounted rotated 90°, so the model only fires when it is turned upright).
- [ ] How the speaker and the microphone are fixed, and how their wires route.
- [ ] Cable routing from the Pi to BiBoard and clearance for the legs.
- [ ] A photo set of the assembled G2: top, side, rear, and the wiring under the lid.
- [ ] The permanent mount, replacing the velcro.

## The case design in progress

The owner is designing a replacement mount with a collaborator: [Bittle X Platform and Pi add-on](https://beetlebugorg.github.io/bittlex/) (3D viewer: [`/viewer/`](https://beetlebugorg.github.io/bittlex/viewer/)). It is a work in progress as of 2026-10-17 and is **not installed on G2 yet**. This section summarises what the project page says; the page is the source, and this one will be updated as the design settles.

- **Idea:** a peg platform that clips onto the stock Petoi Bittle X back cover (four pegs, slide forward 7 mm, click into place, no tools, glue or tape), and a Raspberry Pi add-on that drops onto it.
- **The add-on (v0.24):** a rounded pod with a slide-on top panel holding a Pi Zero 2 W with a PiSugar 2 (1200 mAh); the Petoi AI Vision camera on a camera mount; a 3 W speaker on an NS4168 amplifier; an SPH0645 microphone. Printed parts: pod body, panel, button, camera mount, two low-camera parts for robots without a head, and logos. All print without supports.
- **Same parts as G2's:** the camera, amplifier and microphone match what G2 uses ([`../docs/hardware/as-built.md`](../docs/hardware/as-built.md)). The design uses the PiSugar 2 where G2 has the PiSugar S, so the fit needs checking.
- **Published there:** the platform spec and the add-on build guide as PDFs, print files (`.stl`, `.3mf`), CAD (`.step`) and a packaged download for each of the platform and the add-on.
- **Licenses (per the page):** code MIT; designs and documents CC BY 4.0; the Petoi models used carry no stated license; the PiSugar models are GPL-3.0. Anything copied into this repository should respect those terms; this page links instead of copying.
- **Open:** once the design is installed, replace the "What is on G2 now" table above and fill in the "To be recorded" list.

## History

The first mounting research (a corner-clip design, measurements, and why it was abandoned) is in [`../docs/archive/mounting-research-2026-09.md`](../docs/archive/mounting-research-2026-09.md).
