# Self-righting after a fall

**Status:** G2 can flip himself back over from fully on his back. This was confirmed on G2 on 2026-09-28, untethered and on his own battery, using the firmware's recovery keyframes. The earlier belief that Bittle cannot do this came from a simulation result and from another project's unit, and it was wrong for our hardware.

## How it works (firmware)

Read from the OpenCat source (`PetoiCamp/OpenCat` `InstinctBittle.h`, `OpenCatEsp32` `reaction.h`):

- **`rc`** is the recover skill: a 4-frame keyframe skill that drives the shoulders to about −88° and the knees to about +100° to throw the body over, then settles to a low crouch. Serial token `krc`.
- **`rl`** is a roll-over maneuver (back to belly): 6 frames. Serial token `krl`.
- Other stock recovery poses: `lnd` (landing), `knock`, `dropRec`, `lifted` and `dropped`.
- **The trigger is the IMU, not the infrared remote** (which Bittle X V2 does not support). While gyro balance is on, `dealWithExceptions()` watches for `IMU_EXCEPTION_FLIPPED` (past about 85° of tilt), plays a fall sound and loads `rc`.
- A scripted **push reflex** (`IMU_EXCEPTION_PUSHED`) sidesteps or steps back after a shove, and `IMU_EXCEPTION_OFFDIRECTION` turns in place to correct heading drift.

More detail on the firmware path: [`petoi-firmware-reference.md`](petoi-firmware-reference.md).

## Limits

- **Speed:** self-righting is disabled for fast gaits such as trot, because the robot no longer knows it is flipped, so a fall at speed may not trigger it.
- **The push reflex only fires while standing**, not during a walking gait. A stumble mid-walk is not covered by the firmware; the learned mid-gait catch is complementary.
- **With the Pi in the loop:** `pi_pipeline`'s `RecoveryFSM` (`link/recovery.py`) has flags marked hardware-gated for a possible conflict with the firmware's own flip-triggered `rc`. It is built and tested but not wired in, so today the firmware handles recovery on its own. Retest self-righting with the Pi connected before wiring the FSM in.
- **The simulation cannot show it.** Replaying `rc` and `rl` open-loop in PyBullet recovers 0 of 2 fall states (approximate references, no balance loop, no stable side-lie in the model): [`../rl/getup-sim-replay.md`](../rl/getup-sim-replay.md). Judge self-righting on the robot, not in the sim.

## Testing the get-up moves on the pod payload

With the pod and the AI head on, G2 mostly cannot end up fully on his back (the camera stops him), so the case to test is a fall on his side or front. `pi_pipeline/gait/getup_test.py` runs one firmware get-up move per run from a side lie and reports from the IMU whether he got upright:

```bash
sudo systemctl stop g2-voice            # on the Pi: the voice service holds the serial port; start it again afterwards
python pi_pipeline/gait/getup_test.py rc                  # recover (krc)
python pi_pipeline/gait/getup_test.py rl_rc               # roll over (krl), a pause, then recover (krc)
python pi_pipeline/gait/getup_test.py droprec             # the last-ditch flail (kdropRec)
python pi_pipeline/gait/getup_test.py rc --balance off    # the state the exploration fall handler leaves him in
```

Place him on his side by hand first, on the floor, hands near; never on his back. The script refuses to start if he is upright, and every attempt is appended to `~/g2_runs/getup_results.jsonl`. Results go here when run.

## What it means for the project

- Expect to right G2 by hand sometimes, especially after fast falls and while training new gaits.
- A more robust recovery (IMU flip detection plus a dedicated recovery behavior) remains a possible stretch goal. If it is attempted, test the stock `rc` and `rl` first on the fall types the walking policy produces, and re-author keyframes only if they are unreliable.
- Never put G2 on his back as a test: the Pi and the BiBoard are exposed ([`../guides/operating-g2.md`](../guides/operating-g2.md)).

## History of this page

- **Early research (2026-09-01):** the stock self-right was believed to be narrow: disabled for fast gaits, and one community project reported it does not self-right from a supine fall.
- **Simulation (Run 6):** an RL policy that drives only the 8 walking joints did not learn to right the robot from a full tip-over (0% recovered). That is a simulation result: episodes ended at about 74° of tilt, below the firmware's 85° flip line, so the policy never saw the flipped state, and the scripted keyframes were not available as an action.
- **Correction (2026-09-07):** a real Bittle X was observed flipping itself back over from its back, so the earlier framing was a simulation gap, not a physical limit.
- **Confirmation on G2 (2026-09-28):** done on our own unit, as above.
- **Literature (2026-09-01):** most learned fall-recovery work is on robots with hip abduction (a roll joint), which Bittle lacks, so the self-righting half does not transfer. What does transfer is treating recovery as a separate skill with a switch, trained against harsh disturbances.

## Sources
- Petoi Bittle product page and Doc Center (remote controller, balance and recovery behavior, the BiBoard V1 remote incompatibility).
- `PetoiCamp/OpenCat` and `PetoiCamp/OpenCatEsp32` firmware source.
- `MarcHesse/mhflocke` (a community project that reported no supine self-right; contradicted by our unit).
