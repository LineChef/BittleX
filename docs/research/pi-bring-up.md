# Raspberry Pi Zero 2 W bring-up — research notes + runbook

Written before doing it, from web research (Aug/Sep 2026), so the first hands-on
pass has a map. Sources are linked inline. **This is a learning walkthrough** —
the builder has never used a Raspberry Pi, so every step says *what* and *why*,
and flags the specific ways it bites.

Hardware in hand: **Pi Zero 2 W** (the plain 2 W, header-less? — confirm; plan
lists a *WH* kit with pre-soldered headers), **PiSugar S 1200 mAh**, **SanDisk
32 GB Ultra microSDHC**, **micro-USB power supply**. Not yet here: Bittle X /
BiBoard, Grove Vision AI camera.

Everything below needs only the Pi + card + power (+ the PiSugar for the last
bit). None of it needs the robot.

---

## 0. The headline facts that shape every choice

| fact | consequence |
|---|---|
| 512 MB RAM, soldered, not expandable | the whole voice stack (Vosk ~300 MB runtime + Piper/onnxruntime + Python) barely fits; swap is mandatory, running voice+vision together is doubtful, PyTorch is a bad idea (see §7) |
| 4× Cortex-A53 @ 1 GHz (ARMv8, aarch64) | must run **64-bit** Pi OS for ML wheels; compiles are slow; real-time TTS/STT is not guaranteed — must be measured |
| Wi-Fi `brcmfmac` with power-save **on by default** (Bookworm) | SSH stalls/drops under CPU load until you disable it — *do this first*, it's miserable to diagnose later ([forum](https://forums.raspberrypi.com/viewtopic.php?t=357629)) |
| Bookworm = NetworkManager, config lives in `/boot/firmware/` not `/boot/` | old `wpa_supplicant.conf` / `ssh` file tricks are dead; use the Imager ([zansara](https://www.zansara.dev/posts/2024-01-06-raspberrypi-headless-bookworm-wifi-config/)) |
| **PiSugar S** is a *dumb* UPS — no I²C, no battery %, no voltage query | can only sense "external power present"; battery monitoring must be external or skipped; the fancier PiSugar 2/3 are what the tutorials assume ([PiSugar docs](https://docs.pisugar.com/docs/product-wiki/battery/pisugar-s-series)) |
| serial on the Zero 2 W defaults to the flaky **mini-UART** (`/dev/ttyS0`); the good PL011 is tied to Bluetooth | for a reliable BiBoard link, disable BT and take the PL011 — done in config, no robot needed |

---

## 1. Flash the card (on the Mac, with Raspberry Pi Imager)

1. Install **Raspberry Pi Imager** (`brew install --cask raspberry-pi-imager` or from raspberrypi.com).
2. Choose OS → **Raspberry Pi OS Lite (64-bit)**. *Lite* = no desktop (we're headless). *64-bit* is non-negotiable for the ML packages. Stay on **Bookworm**, not the newer Trixie — Trixie has had headless-Wi-Fi regressions ([industrialmonitordirect](https://industrialmonitordirect.com/blogs/knowledgebase/raspberry-pi-zero-2w-headless-wifi-fix-trixie-vs-bookworm)).
3. Choose Storage → the 32 GB card.
4. **Edit Settings (the gear / "OS customisation")** — this is the whole headless setup, do it now:
   - hostname: e.g. `g2pi`  → reachable as `g2pi.local` via mDNS
   - enable **SSH** → "Allow public-key authentication only", paste your Mac's `~/.ssh/id_ed25519.pub` (make one with `ssh-keygen -t ed25519` if you don't have it)
   - username + password: set a real user (there is **no default `pi` user** on Bookworm — if you skip this you cannot log in)
   - Wi-Fi SSID + password + **Wi-Fi country** (must be set or the radio stays off)
   - locale / timezone / keyboard
5. Write, wait, eject.

Why the Imager and not hand-editing files: Bookworm reads this bundle via
`raspberrypi-sys-mods` on first boot; the pre-Bookworm "drop an empty `ssh` file
and a `wpa_supplicant.conf` in /boot" method **no longer works**
([skyboo.net](https://skyboo.net/2024/02/preparing-headless-sd-card-for-raspberry-pi-zero-2-w-without-raspberry-pi-imager/)).

## 2. First boot + SSH in

1. Card into the Pi, micro-USB power into the **PWR** port (the inner one on the
   Zero 2 W; the outer is USB-data). Plain USB PSU for now, not the PiSugar.
2. Wait 1–3 min (first boot resizes the filesystem and reboots once).
3. From the Mac: `ssh g2pi@g2pi.local`. If `.local` doesn't resolve, find the IP
   from your router and `ssh g2pi@192.168.x.y`.
4. `sudo apt update && sudo apt full-upgrade -y && sudo reboot`.

Gotcha: the green LED. On the Zero 2 W it's mostly a power/activity light; a
solid or irregular blink during first boot is normal. No HDMI attached = no
console, so if SSH never comes up after ~5 min, re-flash and re-check the Wi-Fi
country + SSID/password in Imager settings.

## 3. Kill Wi-Fi power-save (do this before anything heavy)

```bash
sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null <<'EOF'
[connection]
wifi.powersave = 2
EOF
sudo systemctl restart NetworkManager
# verify:
iw dev wlan0 get power_save     # want: "Power save: off"
```

`2` = "force off" in NetworkManager's enum (0 default / 1 ignore / 2 off / 3 on)
([crox.net](https://blog.crox.net/archives/129-Disable-WiFi-Power-Management-on-Raspbian-12-Network-Manager.html)).
Without this, SSH sessions freeze for seconds-to-forever whenever the CPU is
busy — which is *all the time* once training/inference runs.

## 4. Swap / zram (needed — see §0)

Bookworm ships **no** `dphys-swapfile` by default and `zram-generator` is the
modern path ([linuxconfig](https://linuxconfig.org/how-to-enable-zram-on-raspberry-pi)).
Caveat from multiple sources: on a 512 MB box zram is a mixed bag — the zram
device itself costs RAM, so keep it small and back it with a real swapfile
([Pi forum](https://forums.raspberrypi.com/viewtopic.php?t=396095)).

Plan: **small zram (lz4) + a 1 GB SD swapfile as backstop.** Measure which one
actually gets used under load (§8) and adjust.

```bash
# zram, ~128 MB compressed pool, lz4 (cheapest on an A53)
sudo apt install -y systemd-zram-generator
sudo tee /etc/systemd/zram-generator.conf >/dev/null <<'EOF'
[zram0]
zram-size = 128
compression-algorithm = lz4
EOF
sudo systemctl daemon-reload
sudo systemctl start /dev/zram0 || sudo systemctl restart systemd-zram-setup@zram0

# 1 GB swapfile backstop
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw,pri=10 0 0' | sudo tee -a /etc/fstab   # lower pri than zram
# tame swappiness so it prefers zram and doesn't thrash the card:
echo 'vm.swappiness=100' | sudo tee /etc/sysctl.d/99-swap.conf
sudo sysctl --system
free -h ; swapon --show
```

(High `swappiness` is counter-intuitive but correct *when the primary swap is
zram* — you want cold pages compressed into RAM early, not an OOM kill.)

## 5. Serial for the BiBoard link (config only, no robot yet)

Default: `/dev/ttyS0` = mini-UART on GPIO 14/15, `/dev/ttyAMA0` = the PL011,
wired to the Bluetooth modem. Mini-UART's baud is tied to the core clock and
gets unreliable at 115200 under load. Fix — take the PL011, drop Bluetooth
([raspberry.tips](https://raspberry.tips/en/raspberrypi-tutorials/enable-uart-raspberry-pi)):

```bash
sudo raspi-config    # Interface Options → Serial Port:
                     #   login shell over serial? NO
                     #   serial port hardware enabled? YES
# then, in /boot/firmware/config.txt add:
#   enable_uart=1
#   dtoverlay=disable-bt
sudo systemctl disable serial-getty@ttyAMA0.service
sudo systemctl disable hciuart      # BT UART service, now unused
sudo reboot
# after reboot: /dev/ttyAMA0 (alias /dev/serial0) is now on GPIO 14/15 at a stable clock
```

Nothing to test until the BiBoard is wired (RX↔TX crossed, GND↔GND, and per the
plan the Pi's 5 V pin stays **unconnected** — it's powered from the PiSugar).
`pi_pipeline`'s `check_serial ports` / `ping` come later.

## 6. PiSugar S — simpler than the tutorials imply

The PiSugar **S** (not 2, not 3) "functions are almost entirely hardware-based,
does not support I²C communication, and can only detect whether an external
power source is connected... does not support power inquiry"
([PiSugar docs](https://docs.pisugar.com/docs/product-wiki/battery/pisugar-s-series)).

So:
- **No `pisugar-power-manager` software** worth installing — it's built for the
  2/3, which expose battery % over I²C at `0x57`/`0x75`. On the S it has nothing
  to read.
- **No battery-percentage or low-battery signal** for our code. If we want
  "G2 is getting low" we need an external ADC on a Grove analog pin, or we just
  time-box sessions. (Matches the plan's existing note.)
- Physical setup: charge it full over its own micro-USB; pogo-pins mate to the
  Pi's underside test pads; it just passes power through.
- **The one config choice:** the S uses the I²C **SCL** GPIO as an auto-boot
  trigger, which clashes with using the Pi's I²C bus for anything else
  ([PiSugar/PiSugar#17](https://github.com/PiSugar/PiSugar/issues/17),
  [#113](https://github.com/PiSugar/PiSugar/issues/113)). We don't use the Pi's
  I²C for anything (BiBoard = UART, camera = on the BiBoard), so: leave the Pi's
  I²C **disabled** and the PiSugar's auto-boot / button features work fine.
  Only revisit if a future Grove I²C sensor hangs off the Pi directly.

## 7. Deploy `pi_pipeline` to the Pi

`pi_pipeline/` is already a real codebase (link/ voice/ vision/ memory/ + a test
suite), currently developed and tested on the Mac. Getting it onto ARM:

```bash
# on the Pi
sudo apt install -y git python3-venv python3-dev build-essential \
     libportaudio2 libatlas-base-dev   # system libs the wheels need
git clone <repo>  ~/bittleX      # or rsync from the Mac
cd ~/bittleX/pi_pipeline
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt          # pip on Pi OS already uses piwheels.org
pip install -r requirements-audio.txt    # the risky one
python -m pytest                          # link/recovery/memory/skills are offline — expect green
```

**Why the audio install is the fragile step (detail):** packages with compiled
code ship as *wheels* per OS+CPU+Python. If no `linux_aarch64` wheel matches,
pip compiles from source *on the Pi* — needs `-dev` headers (cryptic failures
without them) and can take 20 min–hours and **OOM mid-build** on 512 MB. Per
package:

| package | expectation on Zero 2 W (aarch64, Py 3.11, Bookworm) |
|---|---|
| `numpy` | fine — aarch64 wheels exist (or `apt install python3-numpy`) |
| `sounddevice` | pure-Python, but **dead without `libportaudio2`** from apt |
| `vosk` | ships aarch64 wheels; ~50 MB model on disk, **~300 MB RAM at runtime** ([forum](https://forums.raspberrypi.com/viewtopic.php?t=326417)) |
| `onnxruntime` | historically *the* problem child, but 2025+ has manylinux **aarch64** wheels on PyPI *and* on [piwheels](https://www.piwheels.org/project/onnxruntime/); pin a version whose `cp311` aarch64 wheel exists. Fallback: a named wheel URL. |
| `piper-tts` | pulls `onnxruntime`; real-time on a Pi **5**, lags on a Pi **4** for medium/high voices ([hackster](https://www.hackster.io/sarakit/easy-offline-text-to-speech-on-raspberry-pi-a-tts-guide-255a0f)) → on the Zero 2 W plan for **x_low / low (16 kHz)** voices and *measure* |

Mitigations already implied: run the install **after** §4 (swap up) so a compile
can't OOM; prefer `apt` for `numpy`/PortAudio; keep swappiness high during the
install.

**PyTorch / the RL policy:** installable on 64-bit OS (aarch64 wheels exist) but
`import torch` alone is ~150–250 MB resident — reckless on a 512 MB box also
running Vosk. The Phase-3 policy is a *tiny* MLP (`[256,256]`, 276-in, 8-out) —
a handful of matmuls, sub-millisecond once loaded; the cost is torch's
footprint, not the math. **Answer to the plan's open question:** don't run
PyTorch on the Pi — export the policy to **ONNX** and infer via the
`onnxruntime` that's already there for Piper. Revisit only if that proves
insufficient. (Moot until Phase 6 anyway; RL is paused for hardware.)

## 8. Benchmark the real Pi — `benchmark_pi.py` (to build)

One script, run over SSH, prints a table. Measures the things the plan flags as
untested:

- **RAM baseline**: `free -h` idle after boot; after importing the voice stack;
  during a live STT+TTS exchange. Flag if headroom < ~40 MB.
- **Vosk STT**: wall-time to transcribe a fixed 3–5 s WAV with the small model;
  also streaming latency (partial-result lag).
- **Piper TTS**: synth time for a fixed sentence at `x_low` and `low`; report as
  ×real-time (synth_seconds / audio_seconds — want < 1.0).
- **Claude API**: round-trip latency for a minimal `messages.create` from the
  Pi's network, 5 samples, p50/p95. (Just HTTPS — the SDK installs clean.)
- **Serial**: (later, needs BiBoard) round-trip of a no-op token.
- **Thermals / Wi-Fi**: `vcgencmd measure_temp` and an `ssh`-liveness ping while
  `stress-ng --cpu 4 --timeout 120s` runs — confirms §3 actually took.
- **ONNX policy** (later): load the exported policy, time 1000 `run()` calls.

Deliverable of the bench: a go/no-go on "voice pipeline runs on this Pi in real
time", and numbers to decide voice-only vs voice+vision co-residency.

---

## Open questions — status after this research

| question | answer |
|---|---|
| Serial device name on the Zero 2 W? | `/dev/ttyS0` (mini-UART) by default; **switch to `/dev/ttyAMA0` / `serial0`** via `dtoverlay=disable-bt` for a stable 115200 link. Config file is `/boot/firmware/config.txt` on Bookworm. |
| Can a Pi Zero 2 W run `model.predict()` fast enough? | The MLP is trivial; **run it as ONNX, not PyTorch** (torch's RAM cost is the real problem). Fast enough is very likely; benchmark in §8 when Phase 6 comes. |
| Battery monitoring via PiSugar S? | **No.** The S has no I²C, no fuel gauge, no power query — external ADC or time-boxing only. |
| zram or swapfile? | Both: small lz4 zram + 1 GB SD swapfile backstop, high swappiness. Verify the split under load; some say 512 MB is too little for zram to help — measure. |
| Wi-Fi power-save disable method? | `/etc/NetworkManager/conf.d/wifi-powersave-off.conf` → `wifi.powersave = 2`, restart NetworkManager. |
| Real-time Piper on the Zero 2 W? | **Unknown — the actual risk.** Real-time on Pi 5, lags on Pi 4 for bigger voices. Assume `x_low`/`low` voices; §8 decides. |
| Real-time Vosk on the Zero 2 W? | Small model runs; streaming API keeps latency low; **~300 MB RAM** is the pinch, and small-model accuracy is mediocre. |
| Bookworm vs Trixie? | **Bookworm 64-bit Lite** — Trixie had headless-Wi-Fi regressions. |
| Does the Pi need I²C enabled? | No. Leaving it off also sidesteps the PiSugar auto-boot/I²C clash. |

## Sources
- Headless Bookworm / Imager: [zansara](https://www.zansara.dev/posts/2024-01-06-raspberrypi-headless-bookworm-wifi-config/), [skyboo.net](https://skyboo.net/2024/02/preparing-headless-sd-card-for-raspberry-pi-zero-2-w-without-raspberry-pi-imager/), [industrialmonitordirect (Trixie vs Bookworm)](https://industrialmonitordirect.com/blogs/knowledgebase/raspberry-pi-zero-2w-headless-wifi-fix-trixie-vs-bookworm)
- Wi-Fi power-save: [Pi forum](https://forums.raspberrypi.com/viewtopic.php?t=357629), [crox.net](https://blog.crox.net/archives/129-Disable-WiFi-Power-Management-on-Raspbian-12-Network-Manager.html)
- zram / swap: [linuxconfig](https://linuxconfig.org/how-to-enable-zram-on-raspberry-pi), [Pi My Life Up](https://pimylifeup.com/raspberry-pi-zram/), [Pi forum (Zero 2 swap)](https://forums.raspberrypi.com/viewtopic.php?t=396095)
- UART: [raspberry.tips](https://raspberry.tips/en/raspberrypi-tutorials/enable-uart-raspberry-pi), [Pi forum (double UART on Zero 2 W)](https://forums.raspberrypi.com/viewtopic.php?t=392386)
- PiSugar S: [PiSugar Docs — S series](https://docs.pisugar.com/docs/product-wiki/battery/pisugar-s-series), [PiSugar/PiSugar#17](https://github.com/PiSugar/PiSugar/issues/17), [#113](https://github.com/PiSugar/PiSugar/issues/113)
- onnxruntime on ARM: [piwheels](https://www.piwheels.org/project/onnxruntime/), [onnxruntime build docs](https://onnxruntime.ai/docs/build/eps.html)
- Piper: [hackster TTS-on-Pi guide](https://www.hackster.io/sarakit/easy-offline-text-to-speech-on-raspberry-pi-a-tts-guide-255a0f), [aivideosensei](https://aivideosensei.com/guides/piper-tts-offline-voice-guide)
- Vosk: [alphacephei models](https://alphacephei.com/vosk/models), [Pi forum (Zero 2 W)](https://forums.raspberrypi.com/viewtopic.php?t=326417)
- PyTorch on ARM: [PyTorch realtime-RPi tutorial](https://docs.pytorch.org/tutorials/intermediate/realtime_rpi.html), [KumaTea/pytorch-aarch64](https://github.com/KumaTea/pytorch-aarch64)
