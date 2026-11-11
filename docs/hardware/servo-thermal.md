# Servo thermal management

G2's servos can lose torque suddenly when they are asked for sustained high torque. This page specifies why that happens, how G2 estimates servo heat without a temperature sensor, and what the estimate triggers. The estimator is built, but its constants are placeholders until the bench checks at the end of this page are done.

The torque cliff
----------------

- No temperature sensor: A P1S servo (8 legs and 1 neck, about 3 kg·cm peak torque, coreless motor, alloy gears) has no thermistor, and Petoi publishes no datasheet. What Petoi calls "overheat cutback" is almost certainly over-current protection, not a temperature reading.
- Failure chain: Sustained high torque demand (stance holding, uphill, catching a shove, carrying the payload) gives high winding current at low speed, which is the worst case for heating. A hot winding needs more current for the same torque, so protection trips earlier than the nominal stall spec and mid-task. A joint that freezes mid-stride topples G2.
- Battery interaction: The 2S pack sags toward empty, so a low battery behaves like a hot servo. The risk window is sustained hard work within a charge, such as a long rough or uphill traverse or repeated stumble-catches.
- Damage: Sustained near-stall load wears coreless brushes, fatigues gears and can overheat the servo's driver. This damage is cumulative and not recoverable.
- Available signals: Feedback servos return joint angle (slow, about 10 to 30 Hz), not current or temperature. The board reports the pack voltage.

Behaviour
---------

- Layer 0, always in place: A low target speed (0.10 m/s), a power penalty and torque cutback randomisation in training, and `d` (rest), which de-energises all servos, on every gait-loop exit.
- Layer 1, `ThermalGuard` (`pi_pipeline/gait/thermal_guard.py`): A sensorless I²t estimator keeps a heat value per joint. Heat rises with the square of the estimated torque and falls by Newton cooling toward ambient. Each joint has a tier: GREEN below 50% of the estimated trip, AMBER from 50% to 85%, and RED above 85%. The guard speaks a heads-up per joint ("my left-front leg is getting warm"), and `run_gait.py` logs the hottest tier to the CSV and the ring buffer. It is wired into `run_gait.py`.
- Layer 2, `ThermalGovernor` (`pi_pipeline/behavior/thermal_governor.py`): On AMBER it scales speed to 0.55, softens the gait and hints to avoid uphill. On RED it holds a folded, frame-supported cooldown pose for a minimum time and falls back to sit or rest. Escalation is immediate, de-escalation waits, and a re-spike restarts the hold. The governor is built and tested but not wired into the gait or behavior loop.
- Layer 3, a thermal-aware residual policy that receives per-motor temperatures: Designed, not built, and it needs training.

Interfaces
----------

- Input: Commanded joint targets, feedback-servo tracking error and pack current or voltage form a per-joint torque proxy.
- Output: A snapshot with per-joint tiers and `hottest_tier`, a spoken warning, a log column, and a governor decision (speed scale, soften gait, avoid uphill, hold pose).

Constraints
-----------

- Unvalidated constants: The heating rate, dissipation rate, trip level and the standing pose are guesses that err toward safety. Heat is estimated from commanded motion only, so the thresholds are not calibrated against the real servos.
- No retraining: Layers 1 and 2 change no policy and ship without retraining.

Failure handling
----------------

- A RED joint ends in a cooldown pose, and if that pose cannot be reached, in sit or rest.
- A low battery is read as extra heat load because pack voltage sags under sustained work.

Verification
------------

The bench checks that turn the placeholders into measured constants, run one at a time with G2 on a stand or held by hand:
- Hold a hard stance and note the time until the servo protects itself, which scales the generation rate and the trip level.
- Release a hot servo and record the cooldown curve, which sets the dissipation rate.
- Compare feedback-servo tracking error under a normal hard push with an actual stall, which sets the stall constants.
- Record the mean standing pose, which replaces the placeholder standing angle.
- Cross-check the torque proxy against measured tracking once the loop reads servo feedback.

Sources
-------

- Petoi's servo listing and documentation for the P1S servo (see [Hardware specs](specs.md)).
- Winding-temperature estimation by an I²t model is standard in motor controllers.
- Learning to Balance Motor Thermal Safety and Quadrupedal Locomotion Performance with Residual Policy (arXiv:2605.27046) is the design basis for Layer 3.
