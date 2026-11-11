# Feature flags & staged bring-up

Every major subsystem sits behind a flag so hardware bring-up can turn them on
**one at a time** — if something breaks, it's the subsystem you just enabled.
This is the mechanism behind the day-1 checklist.

Source: `pi_pipeline/features.py`. Config: `G2_FEATURES` in `.env`.
Inspect: `python -m pi_pipeline` (resolved set) · `python -m pi_pipeline --profiles`.

## Configuring

```
G2_FEATURES=""                              # empty -> everything on (p9-full)
G2_FEATURES="profile:p2-gait"               # a bring-up stage
G2_FEATURES="profile:p3-safety, -imu"       # stage + override
G2_FEATURES="-explore, gait:scripted"       # no profile -> start from full, adjust
```

Tokens: `profile:<name>` (first token, the base), `+flag` / `-flag` (bool
flags), `field:value` for the three modes — `gait` (`off|scripted|policy`),
`fall_detect` (`off|alert|act`), `power_profile` (`off|interactive|headless`).
Unknown tokens warn and are skipped. Short profile aliases work (`profile:p2`).

At startup each entry point calls `features.log_summary()` — the resolved set
and any dependency adjustments go to the log **and** to `diag`, so every
session records exactly what ran.

## The flags

- foundation: Flag: `link`; Depends on: —; Meaning: BiBoard serial link
- : Flag: `estop`; Depends on: —; Meaning: master safe-hold: forces all actuation/autonomy off
- sensing: Flag: `imu`; Depends on: link; Meaning: orientation estimate (feeds gait + fall detect)
- : Flag: `fall_detect`; Depends on: imu; Meaning: `off` / `alert` (log only) / `act` (run recovery)
- : Flag: `vision_safety`; Depends on: camera; Meaning: cliff/edge + obstacle, safety-critical
- : Flag: `vision_perception`; Depends on: camera; Meaning: scene / object / individual recognition, novelty
- : Flag: `mic`; Depends on: —; Meaning: audio input stream
- : Flag: `wake_word`; Depends on: mic; Meaning: continuous wake-word vs. push-to-talk
- actuation: Flag: `gait`; Depends on: link, imu; Meaning: `off` / `scripted` (firmware wkF) / `policy` (RL)
- : Flag: `thermal_guard`; Depends on: gait; Meaning: servo thermal protection
- : Flag: `sound_cues`; Depends on: —; Meaning: buzzer / chirp expressive output (≠ TTS)
- : Flag: `leds`; Depends on: —; Meaning: status / listening indicator
- cognition: Flag: `stt`; Depends on: mic; Meaning: speech-to-text
- : Flag: `tts`; Depends on: —; Meaning: text-to-speech
- : Flag: `claude`; Depends on: network; Meaning: LLM conversation layer (text-mode if no stt/tts)
- : Flag: `memory`; Depends on: —; Meaning: persistent store + recall
- : Flag: `personality`; Depends on: —; Meaning: trait biasing + bonds
- autonomy: Flag: `mode_controller`; Depends on: —; Meaning: mode FSM (IDLE / CONVERSE / EXPLORE …)
- : Flag: `explore`; Depends on: gait, vision_safety; Meaning: autonomous wander / investigate
- : Flag: `idle_rest`; Depends on: gait; Meaning: staged ACTIVE→SIT→RESTING descent
- : Flag: `avoidance_act`; Depends on: vision_safety, gait; Meaning: vision avoidance drives the actuator (vs. log only)
- : Flag: `object_gallery`; Depends on: vision, explore; Meaning: B20 recognition-by-instance library — opportunistic capture during explore, off by default
- cross: Flag: `power_profile`; Depends on: —; Meaning: `off` / `interactive` / `headless`
- : Flag: `diag`; Depends on: —; Meaning: black-box logging; kept on for bring-up

## Dependency rules (`Features.resolve()`)

Adjustments are applied and reported, never silent:

- `estop` → `gait=off`, no `explore`/`idle_rest`/`avoidance_act`, `fall_detect` ≤ `alert`
- no `link` → `gait=off`, `fall_detect=off` (+ cascade)
- no `imu` → policy gait falls back to `scripted`, `fall_detect=off`
- `gait=off` → no `explore` / `idle_rest` / `avoidance_act` / `thermal_guard`
- no `vision_safety` → no `avoidance_act`, no `explore` (don't wander blind)
- no `vision` or no `explore` → no `object_gallery` (needs both to mean anything)
- no `mic` → no `stt`, no `wake_word`
- notes-only: `wake_word` without `stt`; `explore` without `mode_controller`;
  `claude` without `stt`/`tts`

## Bring-up profiles

Each = the previous + one layer, so a regression is isolated to the layer just
added:

- `p0-link`: `link`
- `p1-sensing`: `imu`, `fall_detect=alert`
- `p2-gait`: `fall_detect=act`, `gait=scripted`, `thermal_guard`, `leds`, `sound_cues`
- `p3-safety`: `vision_safety`, `avoidance_act`
- `p4-perception`: `vision_perception`
- `p5-voice`: `mic`, `stt`, `tts`, `claude` (push-to-talk)
- `p6-wake`: `wake_word`
- `p7-memory`: `memory`, `personality`
- `p8-autonomy`: `mode_controller`, `explore`, `idle_rest`
- `p9-full`: `gait=policy`, `power_profile=headless` — the default

Bring-up: assemble → `p0-link`, work through the day-1 checklist for that layer,
then advance. Move `gait` to `policy` only after `scripted` is validated on the
stand and floor.

## Wiring status

`features.py` is consulted at these entry points; the rest is follow-up as each
subsystem reaches hardware bring-up.

- [x] `voice/__main__.py` — `mic`, `tts`, `wake_word`, `memory`; logs summary
- [x] `gait/run_gait.py` — `gait` (refuses if `off`), `thermal_guard`; logs summary
- [ ] `vision/__main__.py` — `vision_safety` / `vision_perception` / `avoidance_act`
- [ ] a unified behaviour driver — `mode_controller` / `explore` / `idle_rest`
      (no single entry point yet; wire when it's built)
- [ ] `link/` — `link` / `fall_detect` mode
- [ ] `power/` — apply `power_profile` on startup
- [ ] `claude` text-mode gate in `voice/conversation.py`
