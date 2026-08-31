# Self-Righting After a Fall — Research Notes

How this relates to what the project has already found: **Run 6 (RL, in sim)
showed that a policy driving only the 8 walking joints cannot right the robot
from a full tip-over** — no roll-axis actuation, a missing degree of freedom.
This note is about the *separate* thing: OpenCat's **firmware** has a built-in,
scripted self-right skill. It works, but narrowly, and its limitations line up
almost exactly with the fall types RL training produces. Revisit this once the
vision module (and a proper IMU-fed recovery layer) is in place.

---

## Summary

Bittle has a real, built-in self-righting capability, but it is narrower than the
marketing framing suggests — and has limitations directly relevant to RL
training, where falls will be frequent and messy.

## What's confirmed to work

- Petoi markets Bittle as reminiscent of Boston Dynamics' Spot — climbing steps
  and self-righting after falling from a slope.
- Official docs confirm self-righting after a fall, historically triggered via
  the infrared remote.
- Balance/recovery also applies to standing: the robot can be pushed from the
  sides and will try to recover. This balancing behaviour is active in most
  postures and gaits.

## Key limitations

- **Speed-dependent.** Per Petoi's docs, self-righting is disabled for faster
  gaits such as trot, because the robot no longer knows it is flipped. A natural
  walking/trot gait is the likely outcome of RL training, so **falls at higher
  speed may not trigger self-righting at all.**
- **Fall-direction-dependent.** A research project using Bittle for locomotion
  learning notes it **does not self-right from a supine (upside-down) fall** — it
  must be set upright by hand. Automatic recovery appears to cover only
  side/forward falls, not a full flip onto the back. That project references a
  `--recover` flag that drives the OpenCat stand posture on side/forward falls as
  a way to trigger recovery programmatically.
- **Possible board mismatch.** The self-right-via-remote trigger in some docs is
  tied to the infrared remote system, and **Bittle X V2 (BiBoard V1) does not
  support the infrared remote controller.** The classic trigger path may not
  apply to this board — the real mechanism is likely a serial/software command;
  confirm once hardware is in hand.

## Community context

A maker who built a DIY OpenCat-based robot from raw components lists
self-righting and dynamic balancing as a planned next step requiring an added IMU
— i.e. in the broader hobbyist community, reliable self-righting is treated as
something actively built and tuned, not an out-of-the-box guarantee in every
scenario.

## Implications for this project

- **Expect to right the robot by hand fairly often during RL training,**
  especially early on. Training explores near-randomly at first, which produces
  exactly the fall types automatic recovery doesn't cover (fast, or fully
  upside-down).
- Once basic locomotion RL works, **more robust self-righting is a reasonable
  stretch goal** — IMU-based flip detection plus a dedicated recovery policy,
  along the lines of quadruped-robotics research. Not a Phase 1 requirement.
  This is the "recovery sub-policy" option raised in the Run 7 wrap-up
  (`docs/rl-runs/auto-iteration-log-run7.md`).
- **Confirm the actual self-right trigger for Bittle X V2 / BiBoard V1** directly
  (Petoi support or forum) — the infrared-remote description in some docs does
  not apply to this board. Add the token to `pi_pipeline/link/opencat.py` once
  known.

## Where this plugs in

- **Phase 6 bring-up:** find and test the self-right trigger command; note it in
  `pi_pipeline/link/`.
- **After vision (Phase 8):** with an IMU already feeding the walking policy,
  adding flip/stumble detection + a recovery behaviour is incremental. Combine
  the firmware skill (for the cases it handles) with a learned or scripted
  fallback for the cases it doesn't.

## Sources

- Petoi Bittle product page — self-righting after falling from a slope.
- Petoi Doc Center, Remote Controller — balance/recovery behaviour, the speed
  limitation, and BiBoard V1 / Bittle X V2 remote incompatibility.
- `MarcHesse/mhflocke` (GitHub) — confirms no self-righting from supine falls;
  the `--recover` flag detail.
- Hackster.io, "DIY Indian-Made Petoi Bittle Replica" — community context on
  IMU-based self-righting as an active DIY effort.
