# Phase 7 — Voice + Claude integration (detail)

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> Phase 7. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## Phase 7 — Voice + Claude integration

**Status:** the pipeline runs end-to-end on a dev machine in text mode —
`pi_pipeline/voice/` (own venv). `wake → STT → Claude → TTS → skill`, every
hardware-specific stage behind an interface (`MockActuator`/`SerialActuator`,
`MacTTS`/`PiperTTS`, `TextSTT`/`VoskSTT`, `AlwaysAwake`/`VoskWakeWord`). Claude
replies parsed into spoken text + `perform_skill` / `remember` tool calls.
**Audio backends installed + validated offline (2026-09-10)** — Piper synth →
WAV → Vosk transcribe round-trips at 94 % word recall (`benchmark_pi.py`). A
character mode (`gir`, opt-in, toggleable by voice) rides on the personality
trait system. Remaining: a live-API run (needs a key —
`python -m pi_pipeline.voice.livecheck`), real mic/speaker on the Pi, and the
Pi Zero 2 W voice-stack benchmark.

- [x] **Config-driven Claude client** — `pi_pipeline/config.py` (env: key, model,
      max tokens, timeout, history depth, persona) + `voice/conversation.py`
      (rolling history, retry-on-timeout, memory seam for Phase 9).
- [x] **Response → spoken text + action commands** — `perform_skill` tool;
      `voice/skills.py` maps skill names to OpenCat `k<token>` serial commands;
      one reply can both talk and move.
- [x] **State-cue interface** — `voice/cues.py` (`LogCue` now; buzzer/posture
      later). Chirp vocabulary drafted 2026-09-10 (`behavior/chirps.py`), wired
      into `BehaviorDriver` as `CHIRP` effects 2026-09-10 (see Phase 10).
- [x] **Command acknowledgement (user request 2026-09-10)** — *every* recognised
      local command (`match_local_command` non-`None`) **and** every
      conversational turn fires `DriverInputs.ack` → an un-rate-limited
      `ChirpMood.ACK` "heard you" blip + a `"heard"` cue, *before* the slower
      spoken reply; and a bare skill from Claude with no speech now still gets a
      spoken "Okay". Rationale: a misheard command is immediately audible so it
      can be cancelled ("resume" / activity). `ack` in `_EVENT_BOOLS`; the voice
      loop bridges it via `on_event`.
- [~] **Live API end-to-end check — harness built 2026-09-10, needs a key to run.**
      `pi_pipeline/voice/livecheck.py` (`python -m pi_pipeline.voice.livecheck`) /
      `test_livecheck.py` (skips without a key): a few billed calls that verify a
      plain reply, `perform_skill` parsing on "do a happy wiggle", `remember`
      fact parsing, and the `memory_context` seam. Put `ANTHROPIC_API_KEY` in
      `.env` and run it.
- [x] **Audio backends installed + validated offline (2026-09-10).**
      `requirements-audio.txt` deps are in `pi_pipeline/.venv`
      (`vosk 0.3.44`, `piper-tts 1.7.0`, `sounddevice 0.5.6`, `onnxruntime
      1.23.2`); models fetched (`models/piper` 301 MB incl. `en_US-ryan-low`,
      `models/vosk` 68 MB small-en). New offline-testable methods
      `PiperTTS.synth_to_wav()` / `VoskSTT.transcribe_wav()` + a round-trip test
      (Piper synth → Vosk transcribe) that **passes** — the STT/TTS path works
      end-to-end with no mic/speaker. Still hardware: real mic capture on the Pi,
      speaker playback, and the Pi Zero 2 WH RAM/latency check (`benchmark_pi.py`).
- [x] Speech-to-text — real-mic capture + wake-word gate on the Pi (`voice/stt.py`
      / `wake_word.py` `sounddevice` path) — **working on the real Pi 2026-10-03**
      (see the first-run section below). Health-monitor for the audio + serial
      worker threads is built (`pi_pipeline/util/supervisor.py`).
  - Bookworm's PEP 668 blocks plain `pip install` on-device — use the venv.

#### First voice → Claude → walk run on the real G2 — 2026-10-03

**Result: it works end to end.** "gee two" (wake word) → "walk forward" → Vosk transcript → Claude chose `walk_forward` (about 2.6 s for
the API call) → the Pi sent `kwkF` over `/dev/serial0` → G2 walked → a 5 s gait cap sent the stop command exactly 5.0 s later. G2 was
standing on hard floor. No speaker yet, so replies were printed (`--tts print`); the mic is the SPH0645 on I2S (left channel only,
see `blueprints/biboard-pi-connector.md`).

Run it (on the Pi; start the process in the background and track its pid, don't `pkill -f` a pattern that also appears in your own
command line — that killed the shell twice):

```
cd ~/bittleX
G2_LOG_HEARD=1 nohup pi_pipeline/.venv/bin/python -m pi_pipeline.voice --mode voice \
    --actuator serial --max-gait-s 5 --tts print --no-memory > ~/voice.log 2>&1 &   # drop --max-gait-s to run uncapped
echo $! > ~/voice.pid          # stop it with: kill $(cat ~/voice.pid)
```

`--actuator mock` runs the same loop but only logs the serial command it would send (nothing moves) — use it first. The Pi needs
`ANTHROPIC_API_KEY` in `~/bittleX/.env` and the Vosk + Piper models copied to `~/bittleX/models/` (rsync, not git).

What we learned:

- **Speech recognition is the weak link.** The small Vosk model mishears short phrases: "command mode off" came out as "man mode off",
  "the man load off". "walk forward", "stand up" and the wake word "gee two" were all heard correctly. A second recognition pass
  limited to a few phrases fixed the mishearing on synthesized speech, but it was removed along with the command-mode feature.
  Measured on the Pi: Vosk runs 2.22x slower than real time on a whole file and Piper 1.72x ([`guides/pi-bring-up.md`](../guides/pi-bring-up.md) §8);
  live streaming latency after you stop speaking is still unmeasured.
- **Timing, from the logs:** wake word heard, then the utterance, then about 2 s from "heard" to the walk starting (Claude 2.6 s). A first
  63 s gap in a mock run was just the speaker waiting to talk.
- **Set `G2_FOLLOW_UP_S=0` on the robot (done 2026-10-04).** With the follow-up window open, a basic command meant for G2's own voice module (e.g. "stand up") that
  is said within the window is also heard by the Pi, sent to Claude and acknowledged with the Claude beep. At 0, Claude only ever hears speech that begins
  with "gee two", and the beep means a command went to Claude. The cost is saying "gee two" for every turn.
- **A conversation stays open for ~60 s** (the default when `G2_FOLLOW_UP_S` is unset) after any exchange (the follow-up window), so the next thing you say needs no wake word and goes
  straight to Claude. That is why "stand up" said right after another command still made G2 stand.
- **Claude cannot count steps, but it can now set a duration (added 2026-10-03).** `perform_skill` takes an optional `seconds`
  for looping gaits (walk, trot, crawl): "walk forward for eight seconds" sends `kwkF` and the actuator sends the stop 8 s later. Without
  `seconds` the walk runs until stopped, as before. Values are clamped to 60 s (`skills.MAX_GAIT_SECONDS`); a standing gait cap
  (`G2_MAX_GAIT_S`), if set, is a hard ceiling over any requested duration; one-shot skills ignore it. Checked with the live API and the mock
  actuator only, not yet on G2. Distances are not calibrated: asked to "walk about two metres", Claude guessed 8 s. A real distance needs G2's
  measured walking speed (tape-measured runs at a few durations), then a metres → seconds conversion.
- **The gait cap is an optional switch, off by default.** It makes the serial actuator send the stop after N seconds unless another skill
  or `stop()` arrives first (the stop token is `d`, rest posture, servos off). Turn it on per run with `--max-gait-s 5`, or for every
  run (voice loop and the full app) with `G2_MAX_GAIT_S=5` in `.env`; the flag overrides the setting, and `0` means off. Keep it on while
  testing walks by voice; whether to keep it long term is undecided.
- **Logging the heard transcript is opt-in.** `G2_LOG_HEARD=1` writes each recognised utterance to the log at INFO; without it the
  transcript is not logged (a debug-level line is filtered out by the diag logger's INFO floor).
- **Buzzer cues (added 2026-10-04).** With the real actuator, the voice loop beeps G2's buzzer when a command is on its way to Claude (stage `thinking`), so you
  can tell it heard you with no speaker. The sound is a low rising two-note blip (note 4 then 9, `LOW_CUES` in
  `voice/cues.py`); a longer whistle-style cue was drafted and set aside for now. **Only Claude-bound commands beep by default** (`G2_CUE_STAGES=thinking`); the wake word and local commands like "chirps on" are silent, and
  `listening` / `heard` can be switched back on in that setting. The buzzer volume is set to 10 at start (`G2_BUZZER_VOLUME`, 0 = leave it). Notes are semitone numbers
  (C3 = 14) in the low range because the buzzer is loudest there; listening test 2026-10-04: notes 26/30 faint, 33 and up not heard, 4/8 loudest. Durations are a
  divisor of one second, so a longer note is a *smaller* number. Beeps are skipped while a looping gait is running, because it is unchecked whether a non-skill token
  interrupts the gait. More background and a plan for a larger sound set: [`research/buzzer-sounds.md`](../research/buzzer-sounds.md).
  The end-of-speech window `G2_STT_SILENCE_S` (default 0.5 s) is counted in 0.25 s blocks.
- **Spoken replies on (2026-10-04).** The amp and speaker work (a spoken test phrase and a 440 Hz tone both played through card 0, the voiceHAT/I2S card, which is also the
  ALSA default). Set `G2_TTS=piper` in the Pi's `.env` for spoken replies. The voice is streamed: each finished sentence is synthesised by Piper on one thread while the
  previous one plays on another (`_SpeechWorker`, `PiperTTS.prepare/play`), so a long answer starts after the first sentence and then runs without gaps. The first
  sentence still waits for its own synthesis (Piper is ~1.7x slower than speech on this Pi). While G2 speaks, the BiBoard's own voice module can hear it, so a
  reply containing one of its command words could trigger it; say "be quiet" to G2 first to switch the module off for a session.
- **One shared Vosk model (2026-10-04).** The wake-word detector and the speech-to-text recogniser each used to load their own copy of the acoustic model, the biggest
  thing in the Pi's 416 MB. They now share one (`voice/vosk_model.py`). Before: ~296 MB used, 119 MB available, 308 MB of swap in use with the voice service, Piper and Vosk loaded.
- **Two listeners:** G2's BiBoard has its own offline voice module that listens continuously with no wake word. While it is on, a spoken
  command can reach it as well as the Pi. Its switch is spoken to G2 directly: **"be quiet"** makes it ignore basic commands like "rest",
  **"play sound"** brings them back (with a Do-Re-Mi tone). Do not use the serial route: a lowercase `Xa` silently broke it
  (module said "ok" but the body ignored commands) until an uppercase `XA` restored it; details in
  [`hardware/petoi-firmware-reference.md`](../hardware/petoi-firmware-reference.md). Leave it on ("play sound") when a test ends.
  A voice command to toggle it from the Pi was built and reverted.

Open / next:

- **Paused 2026-10-03 night: G2 ran out of power; resume after a recharge.** State when it stopped:
  - The boot service is **installed and enabled** on the Pi (`pi_pipeline/install_voice_service.sh`, unit `g2-voice`; speech output set
    to print via `G2_TTS=print` in the Pi's `.env`; no gait cap set). It had been stopped by hand for the pause, but it is enabled, so
    **it will start by itself on the next boot and G2 will act on "gee two" commands** (watch logs: `journalctl -u g2-voice -f`; stop:
    `sudo systemctl stop g2-voice`). Not yet verified that it comes up on its own after a power cycle.
  - **The BiBoard's own basic voice commands stopped responding** late in the session (after working earlier), and G2 then lost power.
    Not diagnosed: it may simply have been low battery. After recharging, first say "play sound" (tone = module on); if there is no
    tone, say it again closer, then power-cycle the whole body, then check the dial on the hat ("Voice Command"). Idea not yet tried: unplug
    the Pi's TX2/RX2 jumpers to see if the shared serial line interferes. Never send `X` tokens for this (see the warning in the
    firmware reference).
  - Still to do, in order: confirm the module works after the recharge; the "rest" interrupt test above; verify the service starts on boot;
    decide on the gait cap; speaker and amp, then `G2_TTS=piper`.
- **Resume here (paused 2026-10-03): the "rest" interrupt test.** Goal: confirm G2's own voice module can stop a walk that Claude started.
  Clean version, so the Pi can't also act: (1) the BiBoard module is on (say "play sound", hear the tone); (2) start the Pi loop with
  `--actuator serial --max-gait-s 20` as a backstop; (3) say "gee two", pause, "walk forward"; (4) the moment `walk_forward` is logged,
  kill the Pi loop; (5) say "rest" and note how fast G2 stops; if it doesn't, send `d` over serial. A first attempt with the Pi still
  listening was inconclusive (the Pi misheard "rest" as "stress" and sent `stretch`, then `rest`).
- Decide how a Claude-started walk gets interrupted: the module's "rest" is instant and offline (the Pi's own "emergency stop" has to
  go through slow recognition), and "stop" is not one of its commands.
- Calibrate walking speed so "walk N metres" maps to a real duration (duration itself is done, see above).
- Measure streaming speech-recognition latency, and try a smaller/faster voice or recogniser; replies will be slow to start once the speaker works.
- Speaker and amp (still to wire) unlock spoken replies and the full voice loop; then re-run this test with real TTS.
- Make the voice loop start on boot only once the above stop path is settled; for now it is started by hand.
- [ ] **Text-to-speech + mic input through the robot's own body — parts ORDERED
      2026-09-29, not yet wired.** No mic or speaker was wired to the Pi yet
      (confirmed by the user's own physical check); researched whether
      BiBoard's onboard speaker/mic module could be a shortcut for either
      direction — it can't for either: its only serial interfaces are `T_BEEP`
      (a fixed buzzer-melody format, not audio playback) and `XAa-XAe`
      (canned command language switching, not raw audio capture). No
      community project (Petoi's own official ChatGPT-Bittle example
      included) has actually routed synthesized speech through it either —
      they all play audio from whatever computer runs the script, same as our
      own `--tts mac` test. Full research: `docs/research/community-projects.md`
      Finding 7. **Went with a GPIO-wired I2S solution over USB**, since the
      Pi's one USB data port is reserved for the camera's raw-frame path
      (`docs/hardware/specs.md`: detections over UART, live frames over USB,
      never both at once) — parts ordered:
  - Speaker: [NULLLAB NS4168 I2S Audio Amplifier & 3W Speaker Kit](https://www.amazon.com/NULLLAB-NS4168-Audio-Amplifier-Speaker/dp/B0GV33LRR5)
    (amp + matched speaker, MAX98357A-compatible)
  - Mic: [HiLetgo SPH0645 I2S MEMS Microphone Breakout](https://www.amazon.com/HiLetgo-Microphone-Breakout-SPH0645LM4H-Raspberry/dp/B082KRJW62)
  - Full pinout (confirmed no conflicts with BiBoard's existing 6/8/10, and
    the mic's 3.3V-only power requirement) **and the exact software config
    to run both directions at once** — `dtoverlay=googlevoicehat-soundcard`
    (a stock Bookworm overlay whose pin assignments are an exact match for
    this wiring, confirmed against its own device-tree source, not
    inferred) plus a verify-each-step checklist before wiring
    `pi_pipeline` to it — fully spec'd in
    `blueprints/biboard-pi-connector.md`, nothing left to research at
    install time. Mounting location and method (zip-tie through mounting
    holes if present, else foam tape — not plain velcro, given repeated
    footfall vibration on a walking robot) still open, pending the parts
    physically arriving.
- [ ] `SerialActuator` end-to-end: `XS` "Serial-2" mode on the BiBoard —
      **Pi↔BiBoard link confirmed 2026-09-30** (chirp from the Pi beeps G2, ping
      returns the banner, IMU 5.0 Hz over the Pi's UART). Still to do: confirm
      skill commands land, then the full app run.
- [ ] Confirm this runs independently of the 35+ built-in voice commands (they're
      a separate firmware path; these commands go over serial).
- [ ] A buzzer-pattern / posture implementation of the state cue.
- [ ] Speech-to-text — cloud API vs. local (Whisper/Vosk); affects Pi RAM
      headroom. From similar Pi-based LLM voice robots (SunFounder PiDog docs,
      `marceld23/Ai-Robo-Dog`, `rockywuest/pidog-embodiment` — all target Pi
      4/5 with 2 GB+, so treat as directional):
  - A local always-on wake-word detector (Vosk) that only triggers full STT on
    activation — cheap, avoids constant network calls on a weak board.
  - Local TTS (Piper, e.g. `en_US-ryan-low`) is viable and skips cloud latency.
  - On the Pi Zero 2 WH's small headroom, even lightweight Whisper may be too
    heavy — evaluate Vosk for both wake-word and full STT on real hardware.
  - Health-monitor and auto-restart any long-running audio/hardware threads —
    pidog-embodiment logs worker threads dying silently with no restart.
  - Bookworm's PEP 668 blocks plain `pip install` on-device — use a venv (already
    planned) or `--break-system-packages`.
- [ ] Connect to Claude via the Anthropic API (usage-billed, separate from any
      Claude subscription).
  - Config-driven LLM client (env vars for key/model/timeout) with a request
    timeout tuned for the Pi's slower CPU.
  - Split Claude's response into spoken text + structured action commands
    (PiDog's pattern) — maps onto the OpenCat serial interface, so one reply can
    both talk and trigger a skill.
- [ ] Text-to-speech through the robot's speaker.
- [ ] Confirm this runs independently of the 35+ built-in voice commands (two
      separate systems).
- [ ] A simple state cue (buzzer pattern or posture) for listening / thinking /
      speaking — Claude round-trips will have noticeable latency on this hardware.
