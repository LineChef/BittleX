# Recovery — walk / catch / get-up (detail)

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> the recovery architecture and its hardware tests. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## Recovery — walk / catch / get-up (separate from the gait)

Architecture from the ANYmal recovery work (Lee/Hwangbo/Hutter 2019): a **switch
over separate skills**, not one monolithic policy.

| body state | who handles it |
|---|---|
| walking, upright | the learned residual gait (Phase 3) |
| stumbling (tilted, not down) | the gait's own reactive catch — survive-loop ceiling ~18–25% |
| fallen on a side / front | scripted `rc` skill (`krc`) |
| fallen on its back (supine) | scripted `rl` then `rc` (`krl` → `krc`) |
| the switch | `pi_pipeline/link/recovery.py` — a `RecoveryFSM` on IMU roll/pitch |

Bittle has no roll-axis joint, so a *learned* self-right is off the table (Run 6).
The scripted `rc`/`rl` keyframes lever the body over with the legs; the firmware
also auto-runs `rc` on an IMU-detected flip when gyro assist is on. Full detail:
[`docs/hardware/self-righting.md`](../hardware/self-righting.md).

**Built pre-hardware (2026-09-01):**
- `pi_pipeline/link/opencat.py` — `RECOVER`/`ROLL_OVER`/`BALANCE`/`STAND` tokens.
- `pi_pipeline/link/recovery.py` — `RecoveryFSM(roll, pitch) → RecoveryAction`
  (`NONE` / `RECOVER` / `ROLL_THEN_RECOVER` / `SETTLE` / `GIVE_UP`), with a
  fall debounce, a get-up timeout + bounded retries, and a "needs a human"
  give-up. `ACTION_COMMANDS` maps actions to serial strings. 11 unit tests
  (mock orientation traces + a fake clock).

**On hardware (Phase 4–6):**
- [ ] Test the stock `rc` / `rl` against the fall types training produces; if
      unreliable, re-author the keyframes in Skill Composer.
- [ ] Enable gyro assist (`g`) → the firmware's `IMU_EXCEPTION_PUSHED`
      stand-still push reflex works for free. Decide whether to extend it to
      fire mid-walk (firmware fork or a Pi-side reimplementation).
- [ ] Point `RecoveryFSM` at the real IMU (read roll/pitch over serial), wire
      `ACTION_COMMANDS` through `SerialLink` with a wait between skills, and tune
      the thresholds (`fall_rad`, `supine_rad`, `getup_timeout_s`).
- [x] Test the stock `rc`/`rl` against a real flip — **done 2026-09-28,
      untethered (off USB, on battery), before the Pi was ever wired in**:
      worked, including a full self-right from fully flipped (supine).
      Strongest confirmation yet (our own hardware, not a video) — updates
      `docs/hardware/self-righting.md`'s "does not self-right from supine"
      caveat, which was sourced from a different community project.
      **Risk flagged, not yet resolved:** this tested firmware's *own*
      autonomous IMU-flip auto-`rc`, with `RecoveryFSM` not in the loop at
      all. Once the Pi is wired and `RecoveryFSM` starts deciding
      recovery actions too, the two could conflict — that's exactly what
      `firmware_autorecover_on` and the other `HARDWARE-GATED` flags above
      exist for, but none have been tuned against a real flip yet. Don't
      assume today's success carries over unchanged; retest specifically
      once the Pi is in the loop.
