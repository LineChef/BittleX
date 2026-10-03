# Original text of the plan sections that were condensed

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02.** The plan condenses these sections; the original wording is kept here.


---

<!-- Phases 1–2 -->

## Phase 1 — GitHub repo setup ✅

- [x] Create the repo (single repo, `rl_training/` + `pi_pipeline/` + `docs/`).
- [x] Starter README with goals, hardware, and this roadmap.
- [x] `.gitignore` from the start — secrets, trained models, venvs.
- [x] Secrets policy: `.env`, `config.local.*`, `**/secrets.py`, `**/api_keys.py`
      (documented in `.gitignore`); never committed.
- [ ] Commit incrementally per phase, not one dump at the end (ongoing).

## Phase 2 — Orientation (while hardware ships) ✅ / deferred

- [x] Community Bittle simulator (grgv.xyz/blog/bittle) — done, for gait feel.
- [x] Browse the OpenCat firmware (`PetoiCamp/OpenCat`, `PetoiCamp/OpenCatEsp32`)
      to see how gaits are structured in code. See "How OpenCat gaits are
      structured" below.
- [ ] ~~Petoi's official browser simulator~~ — none exists. The full
      `bittle-x.petoi.com` manual and Doc Center were searched; the only
      simulation options are NVIDIA Isaac Sim (relevant to Phase 3, not a quick
      demo) and OpenCatWeb (a UI for a *real* Pi-mounted robot).
- [ ] Petoi beginner coding curriculum — deferred; jumped ahead to Phase 3.
- [ ] Python fundamentals — deferred; picked up while building Phase 3.

---

<!-- Known risks / honest expectations -->

## Known risks / honest expectations

- Hardware debugging is a different skill than web debugging — no stack traces; a
  fault could be code, wiring, power, or the hardware itself.
- RL gaits will look rougher than an animal's, especially early.
- Sim-to-real rarely works on the first deploy — expect a gap and iteration.
- Full integration (Phase 10) is the hardest, messiest part.

> **2026-09-15 — no flipping/rolling tricks, mounted-payload risk.** The Pi +
> PiSugar stack (~61–78 g) rides on a printed standoff off the rear frame, not
> the molded body shell (`blueprints/biboard-pi-connector.md`) — not
> impact-rated for a hard tumble, and the elevated mass shifts G2's moment of
> inertia off what these tricks were tuned for on a bare unit. `flip`/`flipD`/
> `flipF`/`bf`/`tbl`/`rl`(as a trick)/`bx`/`lucky` excluded from any
> voice/`perform_skill` trick set for the life of this mount. Also skipping
> `excited` — investigated as a turn-in-place substitute, sim showed ~0° net
> yaw, and its likely underlying motion falls in the same excluded bounce/
> tumble category anyway. Full detail: `docs/hardware/petoi-skills-survey.md`.

---

<!-- Decision pending — Petoi AI Head (as first written; the current version is in research/petoi-ai-head-evaluation.md) -->

## Decision pending — Petoi AI Head vs the Raspberry Pi (opened 2026-10-02)

**Status:** the [Bittle AI Head Upgrade Kit](https://www.petoi.com/products/bittle-ai-head-upgrade-kit) ($39, 42 g) is
**ordered, arriving around 2026-10-10**. What isn't answered by Petoi's documentation we find out **first-hand**. The open
questions, hands-on tests, behavior inventory and scorecard are in
[`research/petoi-ai-head-evaluation.md`](../research/petoi-ai-head-evaluation.md).

What it is, as known: a drop-in head with its own microphone, speaker and a camera that can be trained with new recognition
models; it uses Wi-Fi and the XiaoZhi cloud LLM, sends skill codes to the BiBoard over Grove, and needs internet and a free
account. It looks like a one-part replacement for the mic, speaker and camera we planned to wire to the Pi — and possibly
for the Pi itself. **How it would be implemented in our plan, and whether it replaces the Raspberry Pi altogether, is
undecided.** Keeping the Pi is a fully valid outcome if it gives the build real value.

**Criteria for the "does it replace the Pi" call**
1. **Is the scripted gait about as good as the learned gait?** If it is, an RL walking policy may not be needed — though the
   owner would prefer to keep it (it is interesting, and its potential isn't fully tapped). This is the open H1 comparison
   ([`rl/real-walk-log.md`](../rl/real-walk-log.md)): so far V2.1 ~0.118 m/s on hard floor vs scripted ~0.12, both fail on carpet,
   and the FL shoulder servo fault must be fixed before a fair comparison.
2. **Can G2 still do most of the behaviors that make it feel alive** (attentive gaze/sound/novelty reactions, roam and come-here,
   idle-descent/sleep/wake, gestures and chirps, enrollment and recognition, Claude conversation with memory and personality)?
   If yes, that is a point for replacing the Pi. Inventory in the evaluation doc.
3. **The trade-off.** The Pi build means a lot of soldering, wires and mounting, and a heavier body with exposed boards and
   connections (Pi + PiSugar ~61–78 g on a printed standoff, plus mic, amp, camera and wiring still to add) — more vulnerable.
   The head is a single ~42 g module and much more streamlined. The wiring work has been worthwhile as learning and would carry
   to future robots, but robustness and simplicity count. What would be lost in exchange: custom on-robot control and safety
   layers, our Claude/memory path unless the head can be redirected or extended, offline/local voice, the SSH/Python dev loop,
   and data privacy (audio/camera to a third-party cloud), plus cost and vendor dependence.

**Possible outcomes:** A) keep the Pi (head unused); B) Pi + head (head as audio/vision front end, only if it exposes them to a
host); C) head only with Petoi's scripted gaits (gives up the learned policy and our safety layers); D) head only, with our own
logic moved to a server or the head's own processor.

**Steps to test it (when it arrives; detail in the evaluation doc)**
- [ ] Privacy gate before powering it: throwaway account, no household faces/names, read the terms and data policy.
- [ ] Unbox, inspect, weigh; note which open questions Petoi's documentation already answers.
- [ ] Power it alone and measure idle/speaking/peak current; decide if Grove 5 V can feed it.
- [ ] Standalone bench bring-up (Wi-Fi, account, conversation, latency, wake word); then cut Wi-Fi and record what still works.
- [ ] Passively listen to its serial output to the BiBoard: baud, framing, message list, any joint-level tokens.
- [ ] Connect it to G2 with the Pi still installed; check Grove/UART collision with the Pi's Serial-2 (`XS`) link and the voice
      module; re-verify the Pi link and the IMU afterwards.
- [ ] Motion arbitration (Pi and head both commanding the BiBoard); talk-only mode or redirecting its motion output.
- [ ] Camera: training/deployment path, on-device vs cloud and offline, class/input/fps limits, per-person recognition, host access.
- [ ] Audio access: raw mic/speaker from a host, transcripts, text-to-speech in, changing the server (only if the terms allow).
- [ ] Compute and real-time: free CPU/RAM/flash, toolchain, an 80 Hz loop with jitter measured, a small model.
- [ ] Safety and recovery: Wi-Fi drop mid-motion, e-stop independent of the cloud, firmware recovery path before experimenting.
- [ ] Dev loop: logs, debug console, OTA pinning.
- [ ] Weight and balance for each candidate build; update the payload model (H2).
- [ ] Fill the scorecard and decide (A/B/C/D). Do not remove the Pi from the build before then.

---

<!-- Community & support -->

## Community & support

- r/petoi (Reddit) — Petoi's recommended community
- Petoi Forum Archive (petoi.camp)
- `github.com/PetoiCamp/OpenCat` — firmware source
- `github.com/PetoiCamp/NonCodeFiles` — community 3D-print files
- `github.com/ger01d/opencat-gym` — the RL training environment
