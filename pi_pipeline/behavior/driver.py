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

from ..personality.mood import IdleBias, Mood, MoodConfig, MoodModel
from ..personality.traits import BehaviorParams
from ..vision.feed import Frame
from .chirps import ChirpMood, Chirper
from .emergency import EmergencyStop
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
from .sleep_mode import SleepAction, SleepMode, SleepModeConfig, SleepState

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
    CHIRP = "chirp"      # payload: ChirpMood -- an emotive buzzer melody
    POWER = "power"      # payload: "headless" | "interactive" -- Pi power profile
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

    # --- emergency stop (latching, top priority) ---
    halt: bool = False                     # freeze G2 NOW and hold until `release`
    release: bool = False                  # clear a latched emergency stop

    # --- discrete events since the last tick ---
    wake_word: bool = False                 # addressed / wake phrase heard
    conversation_ended: bool = False
    told_stop: bool = False                 # explicit "stop" / "that's enough"
    told_stay: bool = False                 # "stay" / "wait here" -> sit and hold
    told_sleep: bool = False                # "go to sleep" -> deep-idle now (overrides person-present)
    rebuffed: bool = False                  # "leave me alone" / harsh correction -> mood SUBDUED
    picked_up: bool = False                 # lifted this tick (edge of `held`)
    loud_sound: bool = False                # a startling noise -> rouse
    imu_tap: bool = False                   # a tap / knock on the shell -> wake from sleep
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

    # --- mood inputs (from the memory store's recency, fed by the runtime) ---
    last_interaction_s: float | None = None  # seconds since the last exchange (None = unknown)
    exchanges_recent: int = 0                # exchanges within the mood window


@dataclass
class DriverTick:
    mode: Mode
    posture: Posture
    enroll_state: EnrollState
    effects: list = field(default_factory=list)
    reason: str = ""
    mood: Mood = Mood.NEUTRAL
    sleep_state: SleepState = SleepState.AWAKE
    seek_attention: bool = False   # LONELY -> a caller may add a gentle attention wander
    halted: bool = False           # emergency stop is latched


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
                 mood_cfg: MoodConfig | None = None,
                 sleep_cfg: SleepModeConfig | None = None,
                 chirps: bool = True,
                 estop_freeze_token: str = "kbalance",
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
        # base idle timings -- mood scales these each tick (LONELY descends
        # sooner, SUBDUED holds a pose longer). Kept so the scaling is always
        # applied to the original, not compounded.
        self._base_sit_after_s = self.idle.cfg.sit_after_s
        self._base_rest_after_s = self.idle.cfg.rest_after_s
        self.mood_model = MoodModel(mood_cfg, clock=clock)
        self.sleep = SleepMode(sleep_cfg, clock=clock)
        self.estop = EmergencyStop(freeze_token=estop_freeze_token)
        self.chirper = Chirper(clock=clock) if chirps else None
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
        self._prev_sleep = self.sleep.state
        self._seek_attention = False
        self._last_reason = "init"

    @property
    def last_reason(self) -> str:
        return self._last_reason

    # --- chirps ----------------------------------------------------------
    def _chirp(self, mood: ChirpMood, now: float, reason: str = "") -> list:
        """A rate-limited emotive chirp, as a (possibly empty) effect list.
        One shared Chirper across all trigger points -> at most one buzz/tick."""
        if self.chirper is None or not self.chirper.ready(now):
            return []
        self.chirper.fired(now)
        return [Effect(EffectKind.CHIRP, mood, reason or mood.value)]

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
        # sleep wake signals are fed to sleep.update() in the tick's sleep gate
        # (not via on_activity() here -- that would swallow the WAKE action).
        if i.picked_up or i.loud_sound:
            fx += self._chirp(ChirpMood.ALERT, now, "startled")
        if i.rebuffed:
            self.mood_model.note_rebuff(now)
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
            fx += self._chirp(ChirpMood.GREETING, now, "say hi")
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
                happy = self._chirp(ChirpMood.HAPPY, now, f"recognised {lab}")
                if g is not Gesture.NONE:
                    return [Effect(EffectKind.SKILL, GESTURE_TOKEN[g],
                                   f"recognised {lab} after an absence")] + happy
                self._last_reason = f"recognised {lab}, hop on cooldown"
                return happy
        return []

    # --- cliff reflex --------------------------------------------------
    def _cliff_reflex(self, i: DriverInputs, now: float) -> list | None:
        if not self._vision or self.cliff is None or i.edge is None or CliffAction is None:
            return None
        act = self.cliff.update(i.edge)
        if act is CliffAction.NONE:
            return None
        fx = [Effect(EffectKind.DIAG, ("cliff.reflex", act.value), "edge in view")]
        fx += self._chirp(ChirpMood.ALERT, now, f"cliff {act.value}")
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

        # 0. EMERGENCY STOP -- latching, outranks everything. While halted the
        #    driver computes nothing else: just stop + hold until `release`.
        if i.halt:
            self.estop.halt()
        if i.release:
            self.estop.release()
        if self.estop.halted:
            self._choreo.clear()
            return self._finish(self.mode.update(now), self.estop.effects(), now,
                                reason="EMERGENCY STOP (halted)")

        effects += self._apply_events(i, now)

        # --- mood: slow-moving, from interaction recency (fed by the runtime
        #     from the memory store). Scales the idle-descent timing --
        #     LONELY settles sooner and seeks attention; SUBDUED holds longer.
        self.mood_model.update(now, last_interaction_s=i.last_interaction_s,
                               exchanges_recent=i.exchanges_recent)
        bias: IdleBias = self.mood_model.idle_bias()
        self.idle.cfg.sit_after_s = self._base_sit_after_s * bias.sit_mult
        self.idle.cfg.rest_after_s = self._base_rest_after_s * bias.rest_mult
        self._seek_attention = bias.seek_attention

        # --- deep-idle sleep -- the state below IdlePosture RESTING. Sits
        #     above enrollment / choreography / mode: while DOZING / ASLEEP it
        #     owns the robot (no explore, no descent, buzz-free) until a wake
        #     signal (wake word, tap/lift, loud sound, spoken-to, or command).
        if i.told_sleep:
            self.sleep.on_command_sleep()
        _, s_act = self.sleep.update(
            now, resting=self.idle.posture is Posture.RESTING,
            person_present=i.person_present, loud_sound=i.loud_sound,
            imu_tap=i.imu_tap or i.picked_up,          # lifted == a wake
            wake_word=i.wake_word or i.told_stop)      # spoken to == a wake
        if s_act is SleepAction.ENTER_SLEEP:
            effects += [
                Effect(EffectKind.DIAG, ("sleep", "enter"), self.sleep.last_reason),
                *self._chirp(ChirpMood.SLEEPY, now, "going to sleep"),
                Effect(EffectKind.SKILL, "kzz", "curl up to sleep"),
                Effect(EffectKind.POWER, "headless", "sleep: power-save profile"),
                Effect(EffectKind.CAPTURE, ("off", None), "sleep: camera off"),
            ]
            return self._finish(self.mode.update(now), effects, now,
                                reason=f"sleep: {self.sleep.last_reason}")
        if s_act is SleepAction.WAKE:
            effects += [
                Effect(EffectKind.DIAG, ("sleep", "wake"), self.sleep.last_reason),
                Effect(EffectKind.POWER, "interactive", "wake: full-power profile"),
                Effect(EffectKind.CAPTURE, ("on", None), "wake: camera on"),
            ]
            self.idle.on_activity()  # hand back to IdlePosture's own rouse
            if self.idle.posture is Posture.WAKING and self._choreo.label != "wake":
                self._choreo.start("wake", _wake_steps(),
                                   on_done=self.idle.wake_done, now=now)
                effects += self._choreo.pump(now)
            return self._finish(self.mode.update(now), effects, now,
                                reason=f"waking: {self.sleep.last_reason}")
        if self.sleep.asleep:  # DOZING / ASLEEP, no transition -> hold
            return self._finish(self.mode.update(now), effects, now,
                                reason=f"asleep: {self.sleep.last_reason}")

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
        if self.sleep.state is not self._prev_sleep:
            diags.append(Effect(EffectKind.DIAG,
                                ("sleep", f"{self._prev_sleep.value}->{self.sleep.state.value}"),
                                self.sleep.last_reason))
            self._prev_sleep = self.sleep.state
        return DriverTick(mode=mode, posture=self.idle.posture,
                          enroll_state=self.enroll.state,
                          effects=diags + effects, reason=reason,
                          mood=self.mood_model.mood, sleep_state=self.sleep.state,
                          seek_attention=self._seek_attention,
                          halted=self.estop.halted)
