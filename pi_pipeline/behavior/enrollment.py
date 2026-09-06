"""Enrollment mode -- G2 walks a new person through a photo-capture session so a
recogniser model can be trained on them later (B15).

Triggered by "G2, meet <name>". G2 greets them, explains it needs a few sessions
to "get to know" them, then talks them through a scripted set of poses
(look at me / come closer / step back / turn your head / step out of frame),
capturing frames the whole time. Frames are quality-gated by the caller (bright
enough, face big enough); bad stretches get a re-prompt, not counted.

**Three sessions per person**, ideally on separate encounters / spots / lighting,
so the dataset has real variety (one session = one lighting condition -- the
lesson from the 2026-09-06 practice run). G2 says which session this is and how
many remain. `prior_sessions` comes from the caller (e.g. counting
`training_data/faces/<name>/session_*/` markers).

Pure FSM + a clock, like `link/recovery.py` / `behavior/idle_posture.py`. The
caller maps `EnrollAction` onto real behaviour: SPEAK -> TTS, CAPTURE_ON/OFF ->
the serial frame grabber writing to the session dir, ORIENT -> turn to a
bearing, COMPLETE/ABORT -> tear down. Nothing here does I/O.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

SESSIONS_REQUIRED = 3


class EnrollState(Enum):
    IDLE = "idle"
    GREETING = "greeting"       # said hello + the plan, settling before step 1
    CAPTURING = "capturing"     # working through the pose script
    PAUSED = "paused"           # lost the person mid-step, waiting for them back
    DONE = "done"               # this session finished cleanly
    ABORTED = "aborted"         # cancelled, or person gone too long


class EnrollAction(Enum):
    NONE = "none"
    SPEAK = "speak"             # say `tick.speak`
    CAPTURE_ON = "capture_on"   # start saving frames for `tick.step_kind`
    CAPTURE_OFF = "capture_off"
    ORIENT = "orient"           # turn toward `tick.bearing` (if a body is present)
    COMPLETE = "complete"       # session done -- `tick.session_index`, `tick.sessions_left`
    ABORT = "abort"             # `tick.reason`


@dataclass
class EnrollStep:
    kind: str                   # face_center | face_near | face_far | turn | tilt | move | negative
    prompt: str                 # what G2 says to the person
    seconds: float = 4.0        # nominal capture time for this step
    min_frames: int = 8         # ...but don't advance until this many good frames


@dataclass
class EnrollmentConfig:
    greeting_settle_s: float = 3.5      # after the intro, before step 1
    between_step_s: float = 1.2         # pause + next prompt between steps
    max_step_s: float = 12.0           # give up waiting for min_frames after this
    person_lost_grace_s: float = 2.5    # person can drop out this long without pausing
    abort_after_lost_s: float = 20.0    # gone this long -> abort the session
    bad_quality_nudge_s: float = 3.0    # poor face quality this long -> one spoken hint
    sessions_required: int = SESSIONS_REQUIRED


# ---- the pose scripts (varied per session so 3 sessions aren't identical) ----

def build_script(session_index: int) -> list[EnrollStep]:
    """Pose steps for session 1, 2, or 3. Each session leans on a different
    axis of variation."""
    neg = EnrollStep("negative", "Now step out of my view for a moment.", 3.0, 6)
    if session_index <= 1:
        return [
            EnrollStep("face_center", "Look right at me and hold still.", 4.0),
            EnrollStep("face_near", "Bring your face in close.", 4.0),
            EnrollStep("face_far", "Now back up a few steps.", 4.0),
            EnrollStep("turn", "Turn your head slowly left, then right.", 6.0, 12),
            neg,
        ]
    if session_index == 2:
        return [
            EnrollStep("face_center", "Face me again -- if you can, somewhere with different light this time.", 4.0),
            EnrollStep("turn", "Slowly look left... and right... and back.", 7.0, 14),
            EnrollStep("tilt", "Tip your chin up, hold, then down.", 6.0, 12),
            EnrollStep("move", "Take a step to your left.", 3.5),
            EnrollStep("move", "And a step to your right.", 3.5),
            neg,
        ]
    return [  # session 3+
        EnrollStep("face_center", "One more set. Look at me.", 4.0),
        EnrollStep("face_near", "Walk slowly toward me.", 5.0, 12),
        EnrollStep("face_far", "Now slowly walk back.", 5.0, 12),
        EnrollStep("turn", "Turn your head as you move a little.", 6.0, 12),
        neg,
    ]


@dataclass
class EnrollTick:
    state: EnrollState
    action: EnrollAction = EnrollAction.NONE
    speak: str | None = None
    step_kind: str | None = None      # set while CAPTURING
    bearing: float | None = None      # for ORIENT
    session_index: int = 0
    sessions_left: int = 0
    reason: str = ""


class Enrollment:
    def __init__(self, cfg: EnrollmentConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or EnrollmentConfig()
        self._clock = clock
        self._state = EnrollState.IDLE
        self._reason = "idle"
        self._name = ""
        self._session_index = 0
        self._script: list[EnrollStep] = []
        self._step_i = 0
        self._t_state = 0.0      # when the current state started
        self._t_step = 0.0       # when the current step's capture started
        self._good_frames = 0    # good frames seen in the current step
        self._t_lost: float | None = None     # when the person dropped out
        self._t_bad_q: float | None = None     # when face quality went bad
        self._nudged = False

    # --- introspection ---
    @property
    def state(self) -> EnrollState:
        return self._state

    @property
    def last_reason(self) -> str:
        return self._reason

    @property
    def session_index(self) -> int:
        return self._session_index

    @property
    def sessions_left(self) -> int:
        return max(0, self.cfg.sessions_required - self._session_index)

    @property
    def active(self) -> bool:
        return self._state in (EnrollState.GREETING, EnrollState.CAPTURING, EnrollState.PAUSED)

    # --- helpers ---
    def _now(self, now: float | None) -> float:
        return self._clock() if now is None else now

    def _tick(self, action=EnrollAction.NONE, *, speak=None, reason=None,
              step_kind=None, bearing=None) -> EnrollTick:
        if reason:
            self._reason = reason
        return EnrollTick(
            state=self._state, action=action, speak=speak, step_kind=step_kind,
            bearing=bearing, session_index=self._session_index,
            sessions_left=self.sessions_left, reason=self._reason,
        )

    # --- events ---
    def start(self, name: str, prior_sessions: int = 0, now: float | None = None) -> EnrollTick:
        """Begin an enrollment session for `name`. `prior_sessions` = how many
        completed sessions this person already has."""
        t = self._now(now)
        self._name = name.strip() or "you"
        self._session_index = prior_sessions + 1
        req = self.cfg.sessions_required
        if prior_sessions >= req:
            self._state = EnrollState.DONE
            return self._tick(EnrollAction.SPEAK, reason="already enrolled",
                              speak=f"I've already got all the photos I need of {self._name}.")
        self._script = build_script(self._session_index)
        self._step_i = 0
        self._good_frames = 0
        self._t_lost = self._t_bad_q = None
        self._nudged = False
        self._state = EnrollState.GREETING
        self._t_state = t
        left_after = req - self._session_index
        plan = {
            0: f"This one finishes it -- session {self._session_index} of {req}.",
            1: f"This is session {self._session_index} of {req}, one more after this.",
        }.get(left_after, f"This is session {self._session_index} of {req}, {left_after} more after this.")
        return self._tick(
            EnrollAction.SPEAK, reason=f"greeting, session {self._session_index}/{req}",
            speak=f"Nice to meet you, {self._name}. I need {req} sets of photos to get "
                  f"to know you. {plan} Stay in front of me and follow along.",
        )

    def cancel(self, now: float | None = None) -> EnrollTick:
        self._state = EnrollState.ABORTED
        return self._tick(EnrollAction.ABORT, reason="cancelled",
                          speak="Okay, stopping for now.")

    def update(self, now: float | None = None, *, person_present: bool = True,
               face_quality: float = 1.0, good_frames_this_step: int = 0) -> EnrollTick:
        """Advance the FSM.
        - `person_present`: a person is currently detected
        - `face_quality`: 0..1 from the caller (brightness * face-box size etc.);
          below ~0.4 for a while earns a spoken hint
        - `good_frames_this_step`: running count of *accepted* frames since the
          current step's CAPTURE_ON
        """
        t = self._now(now)
        c = self.cfg

        if self._state in (EnrollState.IDLE, EnrollState.DONE, EnrollState.ABORTED):
            return self._tick()

        # --- person tracking (applies to GREETING/CAPTURING/PAUSED) ---
        if not person_present:
            if self._t_lost is None:
                self._t_lost = t
            lost_for = t - self._t_lost
            if lost_for >= c.abort_after_lost_s:
                self._state = EnrollState.ABORTED
                return self._tick(EnrollAction.ABORT, reason="person gone too long",
                                  speak=f"I lost track of you, {self._name}. Find me again "
                                        f"when you're ready.")
            if lost_for >= c.person_lost_grace_s and self._state != EnrollState.PAUSED:
                self._state = EnrollState.PAUSED
                return self._tick(EnrollAction.SPEAK, reason="person left mid-step",
                                  speak="Come back in front of me.")
            return self._tick(reason="waiting for person")
        else:
            was_paused = self._state == EnrollState.PAUSED
            self._t_lost = None
            if was_paused:
                self._state = EnrollState.CAPTURING
                self._t_step = t
                self._good_frames = 0
                step = self._script[self._step_i]
                return self._tick(EnrollAction.CAPTURE_ON, step_kind=step.kind,
                                  reason="resumed", speak="Good -- " + step.prompt)

        # --- GREETING: settle, then start step 1 ---
        if self._state == EnrollState.GREETING:
            if t - self._t_state < c.greeting_settle_s:
                return self._tick(reason="settling after intro")
            self._state = EnrollState.CAPTURING
            self._step_i = 0
            self._t_step = t
            self._good_frames = 0
            self._nudged = False
            step = self._script[0]
            return self._tick(EnrollAction.CAPTURE_ON, step_kind=step.kind,
                              reason="step 1", speak=step.prompt)

        # --- CAPTURING ---
        step = self._script[self._step_i]
        elapsed = t - self._t_step

        # nudge once on sustained poor quality (skip for the 'negative' step)
        if step.kind != "negative" and face_quality < 0.4:
            if self._t_bad_q is None:
                self._t_bad_q = t
            elif not self._nudged and (t - self._t_bad_q) >= c.bad_quality_nudge_s:
                self._nudged = True
                hint = ("Come a little closer." if face_quality < 0.25
                        else "A bit more light on your face, if you can.")
                return self._tick(EnrollAction.SPEAK, reason="quality nudge", speak=hint)
        else:
            self._t_bad_q = None

        enough = good_frames_this_step >= step.min_frames
        timed_in = elapsed >= step.seconds
        maxed = elapsed >= c.max_step_s
        if (timed_in and enough) or maxed:
            self._step_i += 1
            self._nudged = False
            self._t_bad_q = None
            if self._step_i >= len(self._script):
                self._state = EnrollState.DONE
                left = self.sessions_left
                if left == 0:
                    msg = (f"That's all {c.sessions_required} sets, {self._name}. "
                           f"Ask my humans to train me on you now.")
                else:
                    nxt = "one more time" if left == 1 else f"{left} more times"
                    msg = (f"Got it -- that's set {self._session_index}. "
                           f"Find me {nxt} later to finish.")
                return self._tick(EnrollAction.COMPLETE, reason="session complete", speak=msg)
            self._t_step = t
            self._good_frames = 0
            nxt = self._script[self._step_i]
            # emit CAPTURE_OFF/ON around the prompt so the caller can rotate folders
            return self._tick(EnrollAction.CAPTURE_ON, step_kind=nxt.kind,
                              reason=f"step {self._step_i + 1}", speak=nxt.prompt)

        return self._tick(reason=f"capturing step {self._step_i + 1} ({step.kind})",
                          step_kind=step.kind)


# --------------------------------------------------------------------------
# filesystem helpers -- I/O, NOT part of the FSM. The driver uses these to
# feed `prior_sessions` into start() and to route captured frames.
# --------------------------------------------------------------------------

def _slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name.strip().lower()) or "person"


def person_dir(capture_root: str, name: str) -> str:
    return os.path.join(capture_root, _slug(name))


def count_completed_sessions(capture_root: str, name: str) -> int:
    """How many `session_*/` dirs under this person carry a `.done` marker."""
    root = person_dir(capture_root, name)
    if not os.path.isdir(root):
        return 0
    n = 0
    for d in os.listdir(root):
        if d.startswith("session_") and os.path.isfile(os.path.join(root, d, ".done")):
            n += 1
    return n


def new_session_dir(capture_root: str, name: str, session_index: int) -> str:
    """Create + return `.../<name>/session_<index>/` for this run's frames."""
    d = os.path.join(person_dir(capture_root, name), f"session_{session_index}")
    os.makedirs(d, exist_ok=True)
    return d


def mark_session_done(session_dir: str) -> None:
    with open(os.path.join(session_dir, ".done"), "w") as f:
        f.write(datetime.now(timezone.utc).isoformat(timespec="seconds") + "\n")
