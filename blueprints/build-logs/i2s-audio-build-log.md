# I2S microphone and speaker build log

How the Pi's microphone and speaker were chosen, wired, brought up and configured: the part choices and why, connector and splice details as built, the microphone bring-up diagnosis, the speaker bring-up, and the exact software configuration. The wiring as a reference is in [`blueprints/wiring/g2-wiring-guide.html`](../wiring/g2-wiring-guide.html).

## Speaker + mic for Pi-side voice I/O — mic verified 2026-10-03, speaker/amp verified 2026-10-04

`pi_pipeline`'s TTS/STT currently have nowhere to play/capture audio on the
robot itself — see `docs/research/community-projects.md` Finding 7 and
`project_voice_speaker_gap` memory for the full research (BiBoard's own
speaker/mic module can't be repurposed for this — its only interfaces are
`T_BEEP`, a fixed buzzer-melody format, and `XAa`-`XAe`, canned command
language switching; neither is a raw audio channel. No community project
has solved this either).

**Went with GPIO-wired I2S, not USB** — the Pi's one USB data port is
reserved for the Grove Vision camera's raw-frame path (`docs/hardware/
specs.md`: detections travel over UART, live frames over USB, never both
at once), so a USB sound card (the simpler option otherwise) was ruled
out. Two boards ordered, both wiring directly onto the Pi's bare 40-pin
header, no adapter needed:

- **Speaker**: [NULLLAB NS4168 I2S Audio Amplifier & 3W Speaker Kit](https://www.amazon.com/NULLLAB-NS4168-Audio-Amplifier-Speaker/dp/B0GV33LRR5)
  — amp + matched speaker sold together, MAX98357A-compatible pinout
  (`VIN`, `GND`, `BCLK`, `LRCLK`, `DIN`, plus the speaker's own leads into
  the amp board's output terminals, not the Pi).
- **Microphone**: [HiLetgo SPH0645 I2S MEMS Microphone Breakout](https://www.amazon.com/HiLetgo-Microphone-Breakout-SPH0645LM4H-Raspberry/dp/B082KRJW62)
  — the SPH0645LM4H MEMS mic chip itself, on a small breakout (`VIN`,
  `GND`, `BCLK`, `LRCLK`, `DOUT`). **Runs at 1.6&ndash;3.6V only** (confirmed
  against Adafruit's own guide for the same chip) — its `VIN` must go to
  a Pi 3.3V pin, not the 5V pin the amp uses, or it risks damage.

**Full pinout, confirmed no conflicts with each other or with BiBoard's
existing wiring above:**

| Signal | Pi pin | Used by |
|---|---|---|
| BiBoard GND | 6 | already wired |
| BiBoard RX2 | 8 (GPIO14/TXD) | already wired |
| BiBoard TX2 | 10 (GPIO15/RXD) | already wired |
| Mic `VIN` | 1 or 17 (3.3V) | mic only — **not the amp's 5V pin** |
| Amp `VIN` | 2 (5V) | amp only |
| Amp/Mic `GND` | 9 (or any other free ground pin) | shared — all Pi ground pins are one common net |
| Amp/Mic `BCLK` | 12 (GPIO18) | shared **by design** — one I2S clock line, both boards listen to it |
| Amp/Mic `LRCLK` | 35 (GPIO19) | shared **by design**, same reasoning |
| Mic `DOUT` | 38 (GPIO20) | mic only, audio data mic → Pi |
| Amp `DIN` | 40 (GPIO21) | amp only, audio data Pi → amp |

### Connectors, header pins, and the BCLK/LRCLK splice — confirmed 2026-09-30

**Amp ships ready to wire, no soldering needed.** Confirmed from the
listing's own "About this item" bullets: it includes "NS4168 I2S Amp
Board, 4Ω 3W Speaker, and PH2.0 DuPont cable" — a real JST PH2.0
connector on the board plus a pre-terminated cable. Leave that cable
intact rather than cutting into it.

**Mic ships bare — soldering is required regardless of wiring approach.**
Confirmed from its own listing: "Package Included: 1x SPH0645 I2S MEMS
Microphone Breakout Sensor Board" — the board only, no header, no cable.
It has a single row of 6 through-hole pads, silkscreened `3V`, `GND`,
`BCLK`, `DOUT`, `LRCL`, `SEL` (confirmed pin order from the underlying
Adafruit SPH0645LM4H breakout this is cloned from).

**Fix: solder a 6-pin 0.1" (2.54mm) male header strip into the mic's
pads.** Ordered 2026-09-30: [10-pack of 40-pin 2.54mm straight breakaway
male header strips](https://www.amazon.com/Straight-Breakaway-Breadboard-Connector-Electronic/dp/B0H2GY8C5K)
— snap off a 6-pin section for the mic (the rest is spare stock for
future boards, e.g. the screen once one's chosen). This is the only
connector-creation step anywhere in this wiring — the Pi's header and the
amp's PH2.0 cable both already have finished connectors; the existing
female-to-female Dupont jumpers already on hand cover every connection
once the mic's header is on.

**`SEL` must be tied to a fixed level, not left floating.** It's the mic's
channel-select pin (Left vs Right, for stereo setups); tie it to `GND`
(left channel) or `3V` (right). A floating `SEL` can leave the mic's data
line undriven. **As built (2026-10-03): `SEL` runs to Pi pin 39 (a GND
pin)** — every Pi ground pin is the same net, and this avoids stacking a
second socket on the mic's own `GND` header pin. The mic therefore speaks
on the **left channel only**; the right channel records as silence, so
capture software has to read the left channel (or the stereo pair
averaged) as mono.

**BCLK/LRCLK fan-out, final plan — build the splitter by hand from stock
jumper wires, not by buying one.** Superseded two earlier ideas once the
actual connector hardware was confirmed (see below): stacking two Dupont
sockets on one pin turned out to be mechanically marginal (a standard
breadboard-style header pin is ~8-8.5mm exposed, and two female socket
housings need ~8-10mm combined to seat — right at the edge, not
reliable), and soldering the splice directly onto the mic's tiny board
would have defeated the point of a rewireable reference. A pre-made
1-pin female-to-2-female splitter (confirmed to exist, e.g.
[MODDIY](https://www.moddiy.com/products/6474/Dupont-Terminal-Wire-1-Pin-1-to-2-Female-Splitter-Cable-Adapter.html),
$0.99) would have worked, but wasn't worth a 2-week/$10-shipping order
for a 99-cent part — **built from stock instead, 2026-09-30:**

Per shared signal (BCLK and LRCLK — 2 splitters total, built the same
way), splice **three** stock jumper wires together at one soldered joint,
away from either board (not on the mic's pads):
1. A female-to-female wire, keeping its female end — plugs onto the
   **Pi's pin** (12 for BCLK, 35 for LRCLK).
2. A second female-to-female wire, keeping its female end — plugs onto
   the **mic's** now-headered pin.
3. A female-to-**male** wire, keeping its **male** end — plugs directly
   into the **amp's cable**, which is female (confirmed below), no bridge
   pin needed.

Strip the other end of all three, twist together, solder, insulate with
heat-shrink or tape. Electrically identical to a factory-made splitter,
just hand-built — and the soldered joint is sturdier under a walking
robot's vibration than a friction-fit splitter would have been anyway.
`GND` and `VIN` don't fan out at all — each board grounds/powers
independently, only `BCLK`/`LRCLK` need this three-way splice.

**Confirmed from the vendor's own product photos, not just the listing
text:**
- The amp's I2S connector is a real 5-pin PH2.0 JST plug, silkscreened
  `G` `V` `BCLK` `LRCLK` `DIN` in that order — matches the pin table
  above exactly.
- The included cable is **5 separate individual wires**, each ending in
  its own female Dupont-style socket — not one molded 5-pin block. This
  is what makes the bridge-pin plan above actually work: the `BCLK` and
  `LRCLK` wires can be worked with individually without disturbing `G`,
  `V`, or `DIN`.
- The board has **two M4 mounting holes, Lego-compatible** — resolves
  the open mounting question below for the amp specifically (a real
  screw-mount option, better than the zip-tie/foam-tape fallback). No
  equivalent confirmation yet for the mic board.
- The speaker connects via a small 2-pin PH2.0 plug (there's also an
  unused screw-terminal option on the board) — a separate circuit from
  the Pi wiring entirely, included for completeness.

**Amp's GPIO16/pin36 (`CTRL`), soft-resolved.** The vendor's docs
([github.com/nulllaborg/i2s_audio_amplifier_module](https://github.com/nulllaborg/i2s_audio_amplifier_module))
mention a "CTRL pin for level setting," but the board's own product
photos show only the one 5-pin I2S connector — no separate control pin
or pad visible anywhere. Likely means the "smart software tuning"
marketing claim is handled inside the NS4168's own I2S-based logic, not
through a separate wire — leaning toward **nothing to wire here**, though
not 100% certain without the datasheet. Non-blocking either way: the
overlay works the same with pin 36 unwired.

**Full pin-by-pin wiring reference, kept in sync with this file:**
[`blueprints/wiring/g2-wiring-guide.html`](../wiring/g2-wiring-guide.html)
— physical 40-pin header layout, device-to-device lookup tables, and the
same fan-out/SEL notes above, laid out for quick reference when
unplugging/rewiring at the bench.

### Mic bring-up — verified 2026-10-03

Mic wired per the pinout above (3V → pin 1, GND → pin 9, BCLK → pin 12,
LRCL → pin 35, DOUT → pin 38, SEL → pin 39); the amp was connected on 2026-10-04 (next section).

1. `/boot/firmware/config.txt` got `dtparam=i2s=on` and
   `dtoverlay=googlevoicehat-soundcard` (original saved alongside as
   `config.txt.bak-pre-i2s`), then a reboot. `arecord -l` listed the
   `googlevoicehat` capture card.
2. **First captures were a flat constant** (every sample identical on both
   channels), meaning no data reached the Pi. Diagnosis: with GPIO20
   (pin 38, `PCM_DIN`) switched to a plain input with the pull-down on
   (`pinctrl set 20 ip pd`, then `pinctrl get 20`), it stayed **high**, while every
   other spare GPIO fell low. A DOUT wire connected to nothing follows the
   pull-down, so something was driving the line high — a **solder bridge
   between two pads on the mic's new header** (the first header soldered
   on this project). Reflowing/removing the bridge fixed it.
3. **After the fix:** GPIO20 reads low under the pull-down, and
   `arecord -D plughw:0,0 -f S32_LE -r 48000 -c 2 -d 8` captured clear
   speech on channel 0 (about 15,000 distinct sample values, peak roughly a
   quarter of full scale); channel 1 is silent as expected from `SEL` → GND.
   Played back on the Mac (left channel, DC offset removed, gain applied):
   loud and clear.

**Signature to remember:** a capture where every sample on both channels is
the same value means the data line isn't being driven (no mic power, `SEL`
floating, `DOUT` open or shorted, or a solder bridge). The pull-down test in
step 2 separates "open" (reads low) from "shorted/driven" (stays high).
Before powering a freshly soldered header, check each pair of neighboring
pins for continuity.

### Speaker bring-up — verified 2026-10-04

Amp wired per the pinout table above (5 V → pin 2, GND → pin 9, BCLK → pin 12, LRCLK → pin 35, DIN → pin 40), with the speaker on the amp's
2-pin PH2.0 output.

1. `/boot/firmware/config.txt` on the Pi now contains `dtparam=i2s=on`, `dtparam=audio=on` and `dtoverlay=googlevoicehat-soundcard` (alongside
   `dtoverlay=disable-bt`, `enable_uart=1`, `dtoverlay=dwc2,dr_mode=host`, `gpu_mem=16`). No second I2S overlay is loaded.
2. The Pi lists one duplex ALSA card (`snd_rpi_googlevoicehat_soundcar`, "Google voiceHAT SoundCard HiFi") as card 0, device 0, with no `/etc/asound.conf` or `~/.asoundrc`: it is both the playback device (amp + speaker) and the capture
   device (mic). Playback and capture work at the same time on that card.
3. `pi_pipeline` uses the default ALSA device through `sounddevice`, with no explicit device name; the voice loop plays Piper speech, the
   acknowledgement tone and the battery alarms through the amp, and listens through the mic (mic is left channel only, because `SEL` is on GND).
4. The card **cannot be opened twice for capture at once** (a second input stream fails with "Device unavailable"), so the wake-word detector
   and the speech recognizer share one microphone stream (`VoskWakeWord.hand_over`).
5. The amp's volume is set in software: the acknowledgement tone, the battery alarms and the camera ticks play at a few percent of full scale (defaults in
   `pi_pipeline/config.py`: `G2_ACK_PEAK` 0.0225, `G2_ALERT_PEAK` 0.045, `G2_CAMERA_PEAK` 0.045); the card exposes no ALSA mixer controls (`amixer` printed none).

**Mounting (2026-10-06): everything is attached to the Pi case.** The camera is at the front, the speaker at the very back, and the microphone sits on top of the lid, so the weight goes down the spine of the robot. Total weighed mass of G2 with the case, Pi stack, camera, mic and speaker: about 422 g (one weighing, 2026-10-06).

### Software config — the exact overlay, confirmed, not a research task for later

Running both directions (playback + capture) at once on the Pi's one I2S
bus needs a duplex-capable overlay. **This exact pairing already has one,
built into stock Raspberry Pi OS — no custom device tree work needed.**
`googlevoicehat-soundcard` was written for Google's AIY Voice HAT, which
is the same MAX98357-family-amp + I2S-mic combination as what's ordered
here, and its **pin assignments are an exact match for the table above**
(BCLK GPIO18/pin12, LRCLK GPIO19/pin35, mic `DOUT` GPIO20/pin38, amp `DIN`
GPIO21/pin40) — confirmed against the overlay's own source
(`googlevoicehat-soundcard-overlay.dts`, `raspberrypi/linux`), not
inferred. Confirmed still shipping and working on Raspberry Pi OS
**Bookworm** (this project's target OS, `docs/guides/pi-bring-up.md`).

Add to `/boot/firmware/config.txt`:
```
dtparam=i2s=on
dtoverlay=googlevoicehat-soundcard
```
**Don't also add `dtoverlay=max98357a`** — stacking multiple I2S overlays
is a documented footgun (only the last one in the file actually loads).
`googlevoicehat-soundcard` alone covers both the amp and the mic.

One pin the overlay optionally uses that isn't in the table above: GPIO16
(physical pin 36) as an amp-mute/shutdown control line, matching the `SD`
pin some MAX98357-family boards break out — see the NS4168's `CTRL` pin
note above for what's confirmed so far. If there's no such pin on the
real board, the amp just runs unmuted by default and the overlay works
the same without it.

**Verify each step before moving to the next, don't wire everything then
debug all at once:**
1. After adding the two lines and rebooting: `aplay -l` and `arecord -l`
   should both list a card (playback and capture respectively) — this
   confirms the overlay loaded and the kernel sees the hardware, before
   testing actual sound.
2. `speaker-test -t wav -c 2` (or `aplay` a known WAV file) to confirm the
   amp+speaker actually produces sound.
3. `arecord -D plughw:0,0 -f cd -d 5 test.wav` then play it back to
   confirm the mic captures real audio, not silence/noise.
4. **Only then** point `pi_pipeline` at it. Its code
   (`voice/stt.py`/`voice/tts.py`) uses `sounddevice`'s *default* device,
   not an explicit device name — with the Pi Zero having no other audio
   hardware, this new I2S card should become the sole/default ALSA device
   automatically once the overlay loads, needing no extra config. If
   `python -m pi_pipeline.voice --mode voice` doesn't find it, check
   `python -c "import sounddevice as sd; print(sd.query_devices())"`
   first to confirm what the OS considers default before assuming
   `pi_pipeline` itself has a bug.

**Mounting: doesn't need to fit inside the Pi cover.** Initially flagged
as a concern given the cover's cavity is already over budget (PiSugar's
own case doesn't fit inside it either, see below) — resolved: the header
pins are exposed at the case's top cap, so both boards can be wired out
and mounted elsewhere on the frame entirely, same as any other external
accessory. Two open questions, not yet decided:
- **Where**: somewhere away from the head (matches the existing
  `HEAD_MASS_NOM` balance budget reasoning used for Pi/PiSugar placement
  above), close enough to the Pi's header to keep the 5 signal wires per
  board short.
- **How**: **amp — resolved, M4 mounting holes confirmed from its own
  product photos, Lego-compatible.** A real screw mount, not a fallback —
  use it rather than adhesive. **Mic — still open**, no equivalent
  confirmation of mounting holes yet; if it turns out to have none, foam
  tape (not plain velcro, which works loose under a walking robot's
  repeated footfall shock) is the fallback, with a proper printed carrier
  as the eventual upgrade.
