"""The behaviour driver loop -- the runtime that ties the pure-logic modules
(`ModeController`, `Explorer`/`Novelty`, `IdlePosture`, `GesturePicker`,
`Enrollment`, optional `CliffGuard`) into one thing a caller can tick.

Still no I/O. `tick(DriverInputs) -> DriverTick` takes the frame + sensor state +
discrete events for this control step and returns an ordered list of abstract
`Effect`s. A thin binding layer on the robot maps effects onto real actions --
`Effect(SKILL, "kstr")` -> `actuator.perform`, `Effect(SPEAK, text)` -> TTS,
`Effect(CAPTURE, ("on", "face_center"))` -> the frame grabber, `Effect(DIAG, ...)`
-> the session log. On a dev machine the same loop runs against mock feeds and a
fake clock, which is what the tests do.

Priority each tick, highest first:
  1. an active **enrollment** session owns the robot
  2. a running **choreography** (WAKE / settle-before-rest / PEEK) is pumped to
     completion, but a safety event (edge, picked up) still preempts it
  3. **CliffGuard** safety reflex -- stop / back / turn away from a drop-off
  4. **CONVERSE** -- hold attentive, no roaming, no fidgets
  5. **EXPLORE** -- Explorer intent -> walk / turn / investigate (+ a sniff at a
     novel find), no posture descent
  6. **IDLE** -- IdlePosture staged descent (+ idle fidgets when sitting & settled)
Recognition of a bonded person after an absence fires an excited hop in any of
4-6.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from ..personality.traits import BehaviorParams
from ..vision.feed import Frame
from .enrollment import (
    Enrollment, EnrollmentConfig, EnrollAction, EnrollState, EnrollTick,
    count_completed_sessions, new_session_dir, mark_session_done,
)
from .explore import Explorer, ExploreAction, ExploreConfig
from .gestures import GesturePicker, GestureConfig, GESTURE_TOKEN, Gesture
from .idle_posture import (
    IdlePosture, IdlePostureConfig, Posture, PostureAction,
)
from .mode_controller import Mode, ModeConfig, ModeController
from .novelty import Novelty, NoveltyConfig

try:  # CliffGuard is optional -- the driver runs fine with no edge sensing
    from ..vision.cliff_guard import CliffAction, EdgeReading
except Exception:  # pragma: no cover - vision extras missing
    CliffAction = None  # type: ignore
    EdgeReading = object  # type: ignore


class EffectKind(Enum):
    SKILL = "skill"      # payload: OpenCat skill token, e.g. "kstr"
    STOP = "stop"        # halt / rest ('d') -- payload None
    WALK = "walk"        # keep walking; payload: turn bias (rad, + = right)
    TURN = "turn"        # change heading; payload: turn (rad, + = right)
    HEAD = "head"        # head move; payload: "pan_sweep" | "up" | "center" | float bearing
    SPEAK = "speak"      # payload: text
    CAPTURE = "capture"  # payload: ("on", step_kind) | ("off", None)
    CUE = "cue"          # payload: "idle" | "listening" | "thinking" | "speaking"
    DIAG = "diag"        # payload: (event, reason) -- structured-log hook


@dataclass
class Effect:
    kind: EffectKind
    payload: object = None
    reason: str = ""


@dataclass
class DriverInputs:
    now: float | None = None
    frame: Frame = ()                       # vision detections this instant

    # --- discrete events since the last tick ---
    wake_word: bool = False                 # addressed / wake phrase heard
    conversation_ended: bool = False
    told_stop: bool = False                 # explicit "stop" / "that's enough"
    told_stay: bool = False                 # "stay" / "wait here" -> sit and hold
    picked_up: bool = False                 # lifted this tick (edge of `held`)
    loud_sound: bool = False                # a startling noise -> rouse
    nearby_motion: bool = False             # small sound/motion -> PEEK, don't get up
    meet_name: str | None = None            # "G2, meet <name>" -> start enrollment
    cancel_enroll: bool = False
    say_hi: bool = False                     # "say hi" / "wave" voice intent -> greeting gesture

    # --- continuous sensor / perception state ---
    imu_level: bool = True
    imu_stable: bool = True
    held: bool = False                      # currently being held / off the ground
    recovering: bool = False                # a get-up is in progress
    person_present: bool = False
    face_quality: float = 1.0              # 0..1, for enrollment quality nudges
    good_frames_this_step: int = 0         # accepted frames since the last CAPTURE_ON
    edge: object = None                    # EdgeReading | None, for CliffGuard
    known_person_labels: frozenset = frozenset()  # bonded roster -> recognition hop


@dataclass
class DriverTick:
    mode: Mode
    posture: Posture
    enroll_state: EnrollState
    effects: list = field(default_factory=list)
    reason: str = ""


# PostureAction -> the head-up / stretch / stand choreography, as (delay_s, Effect)
def _wake_steps() -> list:
    return [
        (0.0, Effect(EffectKind.HEAD, "up", "wake: head up")),
        (0.4, Effect(EffectKind.SKILL, "kstr", "wake: stretch")),
        (1.6, Effect(EffectKind.SKILL, "kup", "wake: stand")),
    ]


def _settle_steps(rest_token: str) -> list:
    # dog-circling-before-lying-down: a look-around + weight shift, then rest
    return [
        (0.0, Effect(EffectKind.HEAD, "pan_sweep", "settle: look around")),
        (0.7, Effect(EffectKind.HEAD, "center", "settle: weight shift")),
        (1.2, Effect(EffectKind.SKILL, rest_token, "settle: lie down")),
    ]


def _peek_steps() -> list:
    return [
        (0.0, Effect(EffectKind.HEAD, "pan_sweep", "peek: look")),
        (0.8, Effect(EffectKind.HEAD, "center", "peek: back to rest")),
    ]


class _Choreo:
    """A tiny timed-step player. `start(steps, on_done)` queues (delay_s, Effect)
    pairs relative to now; `pump(now)` releases the due ones and fires `on_done`
    once the queue drains."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._queue: list = []          # (due_time, Effect), sorted by due_time
        self._on_done = None
        self._label = ""

    @property
    def busy(self) -> bool:
        return bool(self._queue)

    @property
    def label(self) -> str:
        return self._label

    def start(self, label: str, steps: list, on_done=None, now: float | None = None) -> None:
        t = self._clock() if now is None else now
        self._queue = sorted(((t + d, e) for d, e in steps), key=lambda p: p[0])
        self._on_done = on_done
        self._label = label

    def clear(self) -> None:
        self._queue = []
        self._on_done = None
        self._label = ""

    def pump(self, now: float | None = None) -> list:
        t = self._clock() if now is None else now
        out = []
        while self._queue and self._queue[0][0] <= t:
            out.append(self._queue.pop(0)[1])
        if not self._queue and self._on_done is not None:
            self._on_done()
            self._on_done = None
            self._label = ""
        return out


class BehaviorDriver:
    def __init__(self, params: BehaviorParams | None = None, *,
                 clock=time.monotonic, rng=None,
                 mode_cfg: ModeConfig | None = None,
                 explore_cfg: ExploreConfig | None = None,
                 idle_cfg: IdlePostureConfig | None = None,
                 gesture_cfg: GestureConfig | None = None,
                 enroll_cfg: EnrollmentConfig | None = None,
                 novelty_cfg: NoveltyConfig | None = None,
                 cliff=None,
                 vision_available: bool = True,
                 capture_root: str = "training_data/faces"):
        # vision_available=False: the bot has no obstacle/edge/person detector
        # deployed (only a single-class face model), so every vision-driven
        # behaviour is held -- no EXPLORE roaming, no recognition hop, no cliff
        # reflex, no "G2 meet <name>" enrollment. CONVERSE + IDLE posture still
        # run. Flip it back on once a real detector ships.  Mirrors
        # features.vision; a runtime caller should pass `features.vision` here.
        self._vision = bool(vision_available)
        self.p = (params or BehaviorParams()).clamp()
        self._clock = clock
        mcfg = mode_cfg or ModeConfig()
        if not self._vision and mcfg.allow_explore:
            from dataclasses import replace as _replace
            mcfg = _replace(mcfg, allow_explore=False)
        self.mode = ModeController(self.p, mcfg, clock=clock)
        self.novelty = Novelty(novelty_cfg)
        self.explorer = Explorer(self.p, self.novelty, explore_cfg)
        # personality -> idle timing: use the BehaviorParams knobs unless the
        # caller pinned an explicit config.
        self.idle = IdlePosture(
            idle_cfg or IdlePostureConfig(
                sit_after_s=self.p.idle_sit_secs,
                rest_after_s=self.p.idle_rest_secs),
            clock=clock)
        self.gestures = GesturePicker(gesture_cfg, clock=clock, rng=rng)
        self.enroll = Enrollment(enroll_cfg, clock=clock)
        self.cliff = cliff
        self._capture_root = capture_root
        self._choreo = _Choreo(clock=clock)
        self._session_dir: str | None = None
        self._session_name = ""
        self._explore_target = ""
        self._t_last_activity = clock()
        # transition tracking, for DIAG events
        self._prev_mode = self.mode.mode
        self._prev_posture = self.idle.posture
        self._prev_enroll = self.enroll.state
        self._last_reason = "init"

    @property
    def last_reason(self) -> str:
        return self._last_reason

    # --- event fan-out -----------------------------------------------------
    def _apply_events(self, i: DriverInputs, now: float) -> list:
        fx: list = []
        if i.wake_word:
            self.mode.on_conversation_start()
            self.idle.on_activity()
        if i.conversation_ended:
            self.mode.on_conversation_end()
        if i.wake_word or i.told_stay or i.conversation_ended:
            self._t_last_activity = now
        if i.told_stay:
            self.idle.on_stay_command()
            self.mode.on_activity()
        # anything that should break roaming / rouse from rest
        if i.told_stop or i.picked_up or i.loud_sound:
            self.mode.on_activity()
            self.idle.on_activity()
            self._t_last_activity = now
        # a hard safety event clears an in-flight non-safety choreography
        if (i.picked_up or i.held) and self._choreo.busy and self._choreo.label != "wake":
            self._choreo.clear()
        if i.cancel_enroll and self.enroll.active:
            t = self.enroll.cancel(now)
            fx += self._from_enroll(t, now)
        # "say hi" voice intent -> a greeting gesture, unless enrolment owns the
        # robot or a non-wake choreography is mid-run
        if i.say_hi and not self.enroll.active and not (
                self._choreo.busy and self._choreo.label != "wake"):
            g = self.gestures.greeting(now)
            fx.append(Effect(EffectKind.SKILL, GESTURE_TOKEN[g], "say hi"))
        return fx

    # --- enrollment ------------------------------------------------------
    def _start_enrollment(self, name: str, now: float) -> list:
        prior = 0
        try:
            prior = count_completed_sessions(self._capture_root, name)
        except Exception:  # filesystem not available in a test / dev run
            prior = 0
        t = self.enroll.start(name, prior, now)
        self._session_name = name
        self._session_dir = None
        if self.enroll.state in (EnrollState.GREETING, EnrollState.CAPTURING):
            try:
                self._session_dir = new_session_dir(
                    self._capture_root, name, self.enroll.session_index)
            except Exception:
                self._session_dir = None
            # a real expressive hello alongside the spoken intro
            g = self.gestures.greeting(now)
            fx = [Effect(EffectKind.DIAG, ("enroll.start",
                                           f"{name} session {self.enroll.session_index}"),
                         "meet <name>")]
            if g is not Gesture.NONE:
                fx.append(Effect(EffectKind.SKILL, GESTURE_TOKEN[g],
                                 f"greeting: {g.value}"))
            fx += self._from_enroll(t, now)
            return fx
        return self._from_enroll(t, now)

    def _from_enroll(self, t: EnrollTick, now: float) -> list:
        fx: list = []
        if t.action is EnrollAction.SPEAK and t.speak:
            fx.append(Effect(EffectKind.SPEAK, t.speak, t.reason))
        elif t.action is EnrollAction.CAPTURE_ON:
            fx.append(Effect(EffectKind.CAPTURE, ("on", t.step_kind), t.reason))
            if t.speak:
                fx.append(Effect(EffectKind.SPEAK, t.speak, t.reason))
        elif t.action is EnrollAction.CAPTURE_OFF:
            fx.append(Effect(EffectKind.CAPTURE, ("off", None), t.reason))
        elif t.action is EnrollAction.ORIENT and t.bearing is not None:
            fx.append(Effect(EffectKind.TURN, float(t.bearing), t.reason))
        elif t.action is EnrollAction.COMPLETE:
            if self._session_dir:
                try:
                    mark_session_done(self._session_dir)
                except Exception:
                    pass
            if t.speak:
                fx.append(Effect(EffectKind.SPEAK, t.speak, t.reason))
            fx.append(Effect(EffectKind.DIAG, ("enroll.complete",
                                               f"{self._session_name} #{t.session_index}"),
                             t.reason))
        elif t.action is EnrollAction.ABORT:
            if t.speak:
                fx.append(Effect(EffectKind.SPEAK, t.speak, t.reason))
            fx.append(Effect(EffectKind.DIAG, ("enroll.abort", t.reason), t.reason))
        return fx

    # --- explore --------------------------------------------------------
    def _from_explore(self, i: DriverInputs, now: float) -> list:
        d = self.explorer.decide(list(i.frame), now)
        self._explore_target = d.target
        fx: list = []
        if d.action is ExploreAction.WANDER:
            fx.append(Effect(EffectKind.WALK, 0.0, d.reason))
        elif d.action is ExploreAction.TURN:
            fx.append(Effect(EffectKind.TURN, d.turn, d.reason))
        elif d.action is ExploreAction.APPROACH:
            fx.append(Effect(EffectKind.WALK, d.turn, f"approach {d.target}"))
        elif d.action is ExploreAction.INVESTIGATE:
            fx.append(Effect(EffectKind.STOP, None, f"investigate {d.target}"))
            if abs(d.turn) > 1e-3:
                fx.append(Effect(EffectKind.HEAD, float(d.turn), "orient to find"))
            g = self.gestures.sniff_find(now)
            if g is not Gesture.NONE:
                fx.append(Effect(EffectKind.SKILL, GESTURE_TOKEN[g], "sniff a find"))
        elif d.action is ExploreAction.HOLD:
            fx.append(Effect(EffectKind.STOP, None, d.reason))
        return fx

    # --- posture ------------------------------------------------------
    def _from_posture(self, action: PostureAction, reason: str, now: float) -> list:
        if action is PostureAction.GO_SIT:
            return [Effect(EffectKind.SKILL, "ksit", reason)]
        if action is PostureAction.GO_REST:
            self._choreo.start("settle", _settle_steps("d"), now=now)
            return self._choreo.pump(now)
        if action is PostureAction.WAKE:
            if self._choreo.label != "wake":
                self._choreo.start("wake", _wake_steps(),
                                   on_done=self.idle.wake_done, now=now)
            return self._choreo.pump(now)
        if action is PostureAction.PEEK:
            self._choreo.start("peek", _peek_steps(), now=now)
            return self._choreo.pump(now)
        if action is PostureAction.LIFE_SIGN:
            return [Effect(EffectKind.HEAD, "bob", "breathing")]
        return []

    # --- recognition hop ------------------------------------------------
    def _recognition_hop(self, i: DriverInputs, now: float) -> list:
        if not self._vision or not i.known_person_labels:
            return []
        for det in i.frame:
            lab = getattr(det, "label", "")
            if lab in i.known_person_labels and self.novelty.is_novel_object(lab, now):
                self.novelty.see_object(lab, now)
                g = self.gestures.excited_hop(now)
                if g is not Gesture.NONE:
                    return [Effect(EffectKind.SKILL, GESTURE_TOKEN[g],
                                   f"recognised {lab} after an absence")]
                self._last_reason = f"recognised {lab}, hop on cooldown"
        return []

    # --- cliff reflex --------------------------------------------------
    def _cliff_reflex(self, i: DriverInputs, now: float) -> list | None:
        if not self._vision or self.cliff is None or i.edge is None or CliffAction is None:
            return None
        act = self.cliff.update(i.edge)
        if act is CliffAction.NONE:
            return None
        fx = [Effect(EffectKind.DIAG, ("cliff.reflex", act.value), "edge in view")]
        if act is CliffAction.SLOW:
            fx.append(Effect(EffectKind.WALK, 0.0, "cliff: slow"))
        elif act in (CliffAction.STOP, CliffAction.FREEZE):
            fx.append(Effect(EffectKind.STOP, None, f"cliff: {act.value}"))
        elif act is CliffAction.BACK_UP:
            fx.append(Effect(EffectKind.SKILL, "kbkF", "cliff: back away"))
        elif act is CliffAction.TURN_AWAY_LEFT:
            fx.append(Effect(EffectKind.TURN, -0.6, "cliff: turn away left"))
        elif act is CliffAction.TURN_AWAY_RIGHT:
            fx.append(Effect(EffectKind.TURN, 0.6, "cliff: turn away right"))
        self._last_reason = f"cliff reflex: {act.value}"
        return fx

    # --- the tick ----------------------------------------------------
    def tick(self, i: DriverInputs | None = None) -> DriverTick:
        i = i or DriverInputs()
        now = self._clock() if i.now is None else i.now
        effects: list = []

        effects += self._apply_events(i, now)

        # IdlePosture may have entered WAKING via on_activity() (loud sound,
        # picked up) without update() returning a WAKE action -- arm the rouse
        # choreography here so a single path drives it.
        if self.idle.posture is Posture.WAKING and self._choreo.label != "wake":
            self._choreo.start("wake", _wake_steps(),
                               on_done=self.idle.wake_done, now=now)

        # 1. enrollment owns the robot (needs a person detector -- held without vision)
        if i.meet_name and not self.enroll.active:
            if not self._vision:
                effects.append(Effect(EffectKind.SPEAK,
                                      "I can't see well enough to learn a new face right now.",
                                      "meet <name> refused -- no vision hardware"))
                effects.append(Effect(EffectKind.DIAG, ("enroll.refused", "no vision"),
                                      "vision_available=False"))
            else:
                effects += self._start_enrollment(i.meet_name.strip(), now)
        if self.enroll.active:
            t = self.enroll.update(
                now, person_present=i.person_present,
                face_quality=i.face_quality,
                good_frames_this_step=i.good_frames_this_step)
            effects += self._from_enroll(t, now)
            return self._finish(Mode.CONVERSE, effects, now,
                                reason=f"enrollment: {self.enroll.last_reason}")

        # 2. a running choreography -- unless a safety event this tick (a
        #    non-wake choreo was already cleared in _apply_events on pickup)
        safety = self._cliff_reflex(i, now)
        if self._choreo.busy and safety is None:
            effects += self._choreo.pump(now)
            mode = self.mode.update(now)
            return self._finish(mode, effects, now,
                                reason=f"choreography: {self._choreo.label or 'done'}")
        if safety is not None:
            effects += safety
            self.mode.on_activity()
            self._choreo.clear()
            mode = self.mode.update(now)
            return self._finish(mode, effects, now, reason=self._last_reason)

        mode = self.mode.update(now)

        # 3. CONVERSE -- attentive hold
        if mode is Mode.CONVERSE:
            _, pa = self.idle.update(now, in_conversation=True,
                                     person_present=i.person_present,
                                     handled=i.held)
            effects += self._from_posture(pa, self.idle.last_reason, now)
            return self._finish(mode, effects, now, reason="in conversation")

        effects += self._recognition_hop(i, now)

        # 4. EXPLORE -- roam, no posture descent (ModeController won't enter it
        #    without vision; this guard is belt-and-suspenders)
        if mode is Mode.EXPLORE and self._vision:
            self.idle.update(now, exploring=True, person_present=i.person_present,
                             handled=i.held)
            effects += self._from_explore(i, now)
            return self._finish(mode, effects, now,
                                reason=f"explore: {self._explore_target or 'roaming'}")

        # 5. IDLE -- staged descent + idle fidgets
        safe_to_rest = (i.imu_level and i.imu_stable and not i.held
                        and not i.recovering)
        _, pa = self.idle.update(
            now, person_present=i.person_present, safe_to_rest=safe_to_rest,
            handled=i.held, nudge=i.nearby_motion)
        effects += self._from_posture(pa, self.idle.last_reason, now)

        if self.idle.posture is Posture.SIT and pa is PostureAction.NONE:
            quiet = now - self._t_last_activity
            g = self.gestures.update(now, idle_quiet_s=quiet, can_gesture=i.imu_level)
            if g is not Gesture.NONE:
                effects.append(Effect(EffectKind.SKILL, GESTURE_TOKEN[g],
                                      self.gestures.last_reason))

        return self._finish(mode, effects, now,
                            reason=f"idle: {self.idle.last_reason}")

    # --- wrap-up: prepend DIAG transitions, stamp reason -----------------
    def _finish(self, mode: Mode, effects: list, now: float, *, reason: str) -> DriverTick:
        self._last_reason = reason
        diags: list = []
        if mode is not self._prev_mode:
            diags.append(Effect(EffectKind.DIAG, ("mode", f"{self._prev_mode.value}->{mode.value}"),
                                self.mode.last_reason))
            self._prev_mode = mode
        if self.idle.posture is not self._prev_posture:
            diags.append(Effect(EffectKind.DIAG,
                                ("posture", f"{self._prev_posture.value}->{self.idle.posture.value}"),
                                self.idle.last_reason))
            self._prev_posture = self.idle.posture
        if self.enroll.state is not self._prev_enroll:
            diags.append(Effect(EffectKind.DIAG,
                                ("enroll", f"{self._prev_enroll.value}->{self.enroll.state.value}"),
                                self.enroll.last_reason))
            self._prev_enroll = self.enroll.state
        return DriverTick(mode=mode, posture=self.idle.posture,
                          enroll_state=self.enroll.state,
                          effects=diags + effects, reason=reason)
