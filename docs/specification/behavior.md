---
audience: contributor
kind: reference
---

# Behavior

The behavior subsystem makes G2 act on its own as well as on request. `BehaviorDriver.tick()` is the one place that composes every autonomous behavior.

Behaviour
---------

- Tick: Each tick reads the current inputs (detections, IMU, voice commands, battery) and returns an ordered list of effects (move, chirp, speak, take a picture). It never touches hardware, and bindings turn effects into real actions, so all autonomy can be tested with no robot.
- Modes: `CONVERSE` (a conversation is active, no autonomous movement), `IDLE` (awake and still), `EXPLORE` (walking exploration) and `APPROACH` (a directed come-here walk).
- Phases: Within the one exploration task the driver reports a phase: look (standing or resting and watching), move (walking) or pause (a survey stop, hit sequence or naming look). The phase is read from the mode and the running choreography, and every change is logged.
- Exploration entry: A roam starts only on a spoken request, or on a yes after G2 asks "Can I go exploring?" following 3 minutes of idling. G2 never starts roaming on his own.
- Wall steering: A near wall turns G2 away toward the side with more room. A wall turned away from three times at the same distance within 20 s hands over to the hit sequence.
- Hit sequence: On a wall hit or an IMU contact signal, G2 backs up and turns around toward the open side.
- Survey stops: G2 stops at times for a claw-look picture, using one shared arm stepping, a 0.8 s settle and a dropped stale frame.
- Ending: Every session ends in the verified rest position, and the roam stops its behavior loop before resting.

Interfaces
----------

- Inputs: Detections, IMU, voice events and sensor readings through the runtime.
- Outputs: Effects to the actuator, the narrator, the chirper and the camera.
- Personality: Composable traits (curiosity, mood, bonds and others) shape both the Claude prompt and the behavior parameters.

Parameters
----------

- `G2_WALL_STEER`, `G2_HIT_WALL` and `G2_IMU_CONTACT`: Turn the wall turn-away, the hit sequence and the IMU contact signal on or off (all on)
- `G2_EXPLORE_INPROCESS`: Runs the exploration inside the voice service
- The 300 s default roam length and the leg budget bound a bout.

See [Exploration mode](../guides/exploration-mode.md) for the full list.

Constraints
-----------

- Consistency: A behavior (stand-up, claw look, rest, sag handling, turns, camera use, what a fall is, what a deaf board is) is the same in every mode. It is defined once and the modes only call it: the claw look is the ball chase's sequence (`run_claw_look`), the body limits are in `pi_pipeline/body.py` (a fall is a tilt past 60 degrees for 0.3 s; a board with no motion data for 20 s is deaf), and the guards, the sag recovery and the responses to a fall and to a deaf board are built by `gait/body_guards.py` for every mode. `tools/check_modes.py` fails a commit that builds a second copy, and `docs/specification/mode-exceptions.md` lists the only differences allowed: the ones explicitly requested.
- Emergency stop outranks everything.

Failure handling
----------------

- A failed behavior tick is skipped and the loop continues.
- A fall during a roam stops the session and rests G2.

Verification
------------

- `python -m pi_pipeline.behavior` runs the driver against mocks, and the tests drive it tick by tick.
- Robot: A supervised roam with a hand near, then `python -m pi_pipeline.diag report`.
