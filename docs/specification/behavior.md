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
- Live follow: `g2attend 1 ball live` follows continuously. A camera thread takes pictures back to back (about 2 to 3 a second) and a control loop steers the claw, ten times a second, to where the target was when the newest picture was taken (the claw's pan at that moment, plus a correction at half the offset), so the picture's age does not make it overshoot. With `stream` (`g2attend 1 ball live stream`) the pictures come from the module's own continuous stream, about 4 a second and steady, instead of one request each. The picture is still about half a second to a second old by use, so it follows a hand-speed target. It keeps the bout's focus lock, fall, sag and stop-file handling, and logs every picture and move.
- Active look (the post-punt watch): in the ball goal (setting `post_punt_watch`, on by default) and in `g2punttest`, G2 watches the ball with the claw after a punt instead of taking one picture afterwards. The watch starts standing, right after the punt, and holds until the ball stops or leaves view. When it ends, the claw is centred, G2 lies down in rest and stands up again, and only then does he say target acquired or turn toward where the ball was last seen. In the goal, the result is the attempt's after-punt reading, and the next attempt starts from where the ball stopped, or turns toward where it was last seen. `g2punttest` stands G2 up, punts the ball, and watches it. The camera stream starts at once; he goes to the attention pose and raises the claw; the claw follows the ball until its world bearing (the claw's direction plus the ball's offset in the picture) and size have stayed put for about 1.5 s, or 10 s pass. Then one picture fixes where it is. Found: he says "target acquired" and the chase goes on from that reading (rest, the eased stand-up, a turn toward it, the walk, the claw range, one more punt). Lost: he says "I lost it", turns 40 degrees toward the side it was last seen on and does the normal claw look. `g2punttest dry` only watches a ball rolled by hand.
- Camera probes: `g2stream` asks the module for a continuous stream of pictures and reports pictures a second and the gaps, and `g2liftcal` steps the claw lift down from 120 with a ball fixed in view and records the picture's vertical shift and the body tilt at each step, to decide whether the live follow can also tilt the camera. Both are hardware tests. The lift calibration showed the picture does not move when the lift changes (the view is the same at lifts of 120 to 60), so the claw cannot follow a target up and down; only the pan follows it.
- Attentive bout: A supervised bout (`g2attend`, run only with someone watching) holds the attention pose with the claw raised and, for a few minutes, turns the camera toward what the camera model detects (largest first), slowly (a move at most every 1.5 s and only part of the way, because the frames are about a second old). After 10 s of following he only glances, and he looks around when nothing is in view. It stops on a fall, a sag, or the stop file, holds the focus lock, and always ends with the claw down and centred and the standard stand-up. It never walks. The camera model has three classes and no human or face class, so it follows detections of those classes, and with a named target it also finds that object with the object gallery (the recognizer exploration uses to name objects), read-only. The target `ball` is the green ball, found by the ball chase's colour finder. The bout is switched off: it refuses to run unless `G2_ATTENTIVE_BOUT=1` is set, because the active look after a punt replaced it.

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

- Move gate: before every move the chase, the goals and the drills send (walk, turn, back, punt), the body's tilt is read. More than 12 degrees off level on pitch or roll and the move is not sent: G2 goes down into the attention pose and stands up again through rest, then the move goes. A tilt past the fall angle is not a sag: he is laid in rest, no stand-up is sent, and the move reports a fall so the session stops. The gate is in the standing flow's stand-up check, so it applies to every mode that moves through it.
- Consistency: A behavior (stand-up, claw look, rest, sag handling, turns, camera use, what a fall is, what a deaf board is) is the same in every mode. It is defined once and the modes only call it: the claw look is the ball chase's sequence (`run_claw_look`), the body limits are in `pi_pipeline/body.py` (a fall is a tilt past 60 degrees for 0.3 s; a board with no motion data for 20 s is deaf), and the guards, the sag recovery and the responses to a fall and to a deaf board are built by `gait/body_guards.py` for every mode. `tools/check_modes.py` fails a commit that builds a second copy, and `docs/specification/mode-exceptions.md` lists the only differences allowed: the ones explicitly requested.
- Claw look and walking: The claw look never starts while a policy walk is running. It waits up to 8 s for the walk to end and, if the walk is still going, is skipped, so the arm and the attention pose never compete with the walking legs.
- Focus lock: While the lock is held (a goal session, an exploration, or `g2focus on`), G2's own initiative stands aside: no "Can I go exploring?" ask, no sit, rest or sleep descent, no idle fidgets and no look-around bouts. Spoken commands, the stop words, the emergency stop, the fall and battery guards and a roam someone asked for are never held back. Each holder expires on its own (a run's hold within 60 s of a crash, a person's within 4 h at most), and every held-back behavior is logged and counted. Every autonomous behavior asks one function, `focus.allow(kind)`.
- Emergency stop outranks everything.

Failure handling
----------------

- A failed behavior tick is skipped and the loop continues.
- A fall during a roam stops the session and rests G2.

Verification
------------

- `python -m pi_pipeline.behavior` runs the driver against mocks, and the tests drive it tick by tick.
- Robot: A supervised roam with a hand near, then `python -m pi_pipeline.diag report`.
