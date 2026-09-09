import random

from pi_pipeline.behavior import (
    BehaviorDriver, DriverInputs, EffectKind, Mode, Posture,
)
from pi_pipeline.behavior.enrollment import EnrollState
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.vision.feed import Detection
from pi_pipeline.vision.cliff_guard import CliffGuard, EdgeReading


class Clk:
    # start well past zero: monotonic() is seconds-since-boot on real hardware,
    # so gesture cooldowns (which compare against a 0.0 "never fired" sentinel)
    # are never in-window at driver start.
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


def det(label, area_side=0.3, bearing=0.5, conf=0.9):
    s = area_side
    return Detection(label, conf, bearing - s / 2, 0.5 - s / 2, s, s)


def kinds(tick):
    return [e.kind for e in tick.effects]


def payloads(tick, kind):
    return [e.payload for e in tick.effects if e.kind is kind]


def _mk(**kw):
    c = Clk()
    # a G2 that never wanders on its own unless the test wants it
    p = kw.pop("params", BehaviorParams(idle_secs_before_explore=1e9,
                                        idle_sit_secs=20, idle_rest_secs=90))
    return BehaviorDriver(p, clock=c, rng=random.Random(0), **kw), c


# --- idle staged descent ------------------------------------------------

def test_idle_descends_active_sit_then_settle_choreo_to_rest():
    d, c = _mk()
    assert d.tick().mode is Mode.IDLE and d.tick().posture is Posture.ACTIVE

    c.adv(21)
    t = d.tick()
    assert t.posture is Posture.SIT
    assert ("ksit" in payloads(t, EffectKind.SKILL))
    assert any(e.payload == ("posture", "active->sit") for e in t.effects
              if e.kind is EffectKind.DIAG)

    c.adv(91)
    t = d.tick()                                   # SIT -> RESTING: settle choreo starts
    assert t.posture is Posture.RESTING
    heads = payloads(t, EffectKind.HEAD)
    assert "pan_sweep" in heads                    # look-around before lying down
    assert "d" not in payloads(t, EffectKind.SKILL)  # rest skill is later in the sequence

    c.adv(1.5)
    t = d.tick()
    assert "d" in payloads(t, EffectKind.SKILL)    # ...now it lies down


def test_activity_from_rest_runs_wake_choreo_then_returns_active():
    d, c = _mk()
    c.adv(21); d.tick()
    c.adv(91); d.tick()
    c.adv(2); d.tick()                             # fully resting
    assert d.idle.posture is Posture.RESTING

    t = d.tick(DriverInputs(loud_sound=True))
    assert t.posture is Posture.WAKING
    assert "up" in payloads(t, EffectKind.HEAD)

    c.adv(0.5); t = d.tick()
    assert "kstr" in payloads(t, EffectKind.SKILL)
    c.adv(1.2); t = d.tick()
    assert "kup" in payloads(t, EffectKind.SKILL)
    c.adv(0.1); d.tick()                           # queue drains -> wake_done()
    assert d.idle.posture is Posture.ACTIVE


def test_picked_up_preempts_a_settle_choreo():
    d, c = _mk()
    c.adv(21); d.tick()
    c.adv(91); t = d.tick()                        # settle choreo in flight
    assert d._choreo.busy

    t = d.tick(DriverInputs(picked_up=True, held=True))
    assert t.posture is Posture.WAKING             # roused, not lying down
    assert "up" in payloads(t, EffectKind.HEAD)


# --- explore ----------------------------------------------------------

def test_explore_investigates_novel_object_with_a_sniff():
    p = BehaviorParams(idle_secs_before_explore=10, investigate_secs=3.0,
                       approach_novelty=False)
    d = BehaviorDriver(p, clock=(c := Clk()), rng=random.Random(0))
    c.adv(11)
    t = d.tick(DriverInputs(frame=[det("mug", area_side=0.45, bearing=0.5)]))
    assert t.mode is Mode.EXPLORE
    assert EffectKind.STOP in kinds(t)             # hold to look
    assert "ksnf" in payloads(t, EffectKind.SKILL)  # sniff a find


def test_explore_wanders_when_nothing_new():
    p = BehaviorParams(idle_secs_before_explore=10)
    d = BehaviorDriver(p, clock=(c := Clk()), rng=random.Random(0))
    c.adv(11)
    t = d.tick(DriverInputs(frame=[]))
    assert t.mode is Mode.EXPLORE
    assert EffectKind.TURN in kinds(t) or EffectKind.WALK in kinds(t)


# --- conversation ---------------------------------------------------

def test_wake_word_enters_converse_and_holds_still():
    d, c = _mk()
    t = d.tick(DriverInputs(wake_word=True))
    assert t.mode is Mode.CONVERSE
    assert EffectKind.WALK not in kinds(t) and EffectKind.TURN not in kinds(t)
    c.adv(5)
    t = d.tick(DriverInputs())
    assert t.mode is Mode.CONVERSE                 # stays until conversation_ended
    t = d.tick(DriverInputs(conversation_ended=True))
    assert t.mode is Mode.IDLE


# --- enrollment ---------------------------------------------------

def test_meet_name_greets_then_drives_the_capture_script(tmp_path):
    d, c = _mk(capture_root=str(tmp_path))
    t = d.tick(DriverInputs(meet_name="Sam", person_present=True))
    assert d.enroll.state is EnrollState.GREETING
    speaks = payloads(t, EffectKind.SPEAK)
    assert speaks and "Sam" in speaks[0]
    # an expressive greeting fired alongside the intro
    assert any(e.kind is EffectKind.SKILL for e in t.effects)

    c.adv(4)                                       # past greeting_settle_s
    t = d.tick(DriverInputs(person_present=True))
    assert d.enroll.state is EnrollState.CAPTURING
    caps = payloads(t, EffectKind.CAPTURE)
    assert caps and caps[0][0] == "on"


def test_enrollment_owns_the_robot_over_idle_and_explore(tmp_path):
    d, c = _mk(capture_root=str(tmp_path))
    d.tick(DriverInputs(meet_name="Sam", person_present=True))
    c.adv(200)                                     # long enough that idle would rest
    t = d.tick(DriverInputs(person_present=True))
    assert t.mode is Mode.CONVERSE                 # enrollment reports as CONVERSE
    assert "d" not in payloads(t, EffectKind.SKILL)  # no lie-down while enrolling


# --- recognition hop ---------------------------------------------

def test_known_person_after_absence_triggers_one_excited_hop():
    p = BehaviorParams(idle_secs_before_explore=1e9)
    d = BehaviorDriver(p, clock=(c := Clk()), rng=random.Random(0))
    roster = frozenset({"sam"})
    t = d.tick(DriverInputs(frame=[det("sam")], known_person_labels=roster))
    assert "kjpF" in payloads(t, EffectKind.SKILL)

    c.adv(2)
    t = d.tick(DriverInputs(frame=[det("sam")], known_person_labels=roster))
    assert "kjpF" not in payloads(t, EffectKind.SKILL)   # not seen as "after absence"


# --- cliff reflex ----------------------------------------------

def test_cliff_reflex_preempts_explore():
    p = BehaviorParams(idle_secs_before_explore=5)
    d = BehaviorDriver(p, clock=(c := Clk()), rng=random.Random(0), cliff=CliffGuard())
    c.adv(6)
    edge = EdgeReading(present=True, dist_norm=0.15, bearing_norm=0.0, confidence=1.0)
    t = d.tick(DriverInputs(edge=edge, frame=[]))
    assert any(e.kind is EffectKind.DIAG and e.payload[0] == "cliff.reflex"
               for e in t.effects)
    assert EffectKind.WALK not in kinds(t)         # not still cruising toward the drop


# --- personality knob wiring ---------------------------------

def test_behavior_params_drive_idle_sit_timing():
    p = BehaviorParams(idle_secs_before_explore=1e9, idle_sit_secs=5, idle_rest_secs=200)
    d = BehaviorDriver(p, clock=(c := Clk()))
    c.adv(4); assert d.tick().posture is Posture.ACTIVE
    c.adv(2); assert d.tick().posture is Posture.SIT     # sat at 5s, not the 20s default


# --- vision_available=False: all vision-driven behaviour held ----------

def test_no_vision_never_enters_explore():
    p = BehaviorParams(idle_secs_before_explore=5)          # would wander fast
    d = BehaviorDriver(p, clock=(c := Clk()), rng=random.Random(0),
                       vision_available=False)
    for _ in range(6):
        c.adv(10)
        t = d.tick(DriverInputs(frame=[det("mug", 0.5)]))
        assert t.mode is not Mode.EXPLORE                   # stays IDLE, descends instead
    assert t.posture in (Posture.SIT, Posture.RESTING)


def test_no_vision_skips_recognition_hop():
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=Clk(), rng=random.Random(0), vision_available=False)
    t = d.tick(DriverInputs(frame=[det("sam")],
                            known_person_labels=frozenset({"sam"})))
    assert "kjpF" not in payloads(t, EffectKind.SKILL)


def test_no_vision_skips_cliff_reflex():
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=Clk(), rng=random.Random(0),
                       cliff=CliffGuard(), vision_available=False)
    edge = EdgeReading(present=True, dist_norm=0.15, bearing_norm=0.0, confidence=1.0)
    t = d.tick(DriverInputs(edge=edge, frame=[]))
    assert not any(e.kind is EffectKind.DIAG and e.payload[0] == "cliff.reflex"
                   for e in t.effects)


def test_no_vision_refuses_enrollment(tmp_path):
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=Clk(), rng=random.Random(0),
                       vision_available=False, capture_root=str(tmp_path))
    t = d.tick(DriverInputs(meet_name="Sam", person_present=True))
    from pi_pipeline.behavior.enrollment import EnrollState
    assert d.enroll.state is EnrollState.IDLE               # never started
    speaks = payloads(t, EffectKind.SPEAK)
    assert speaks and "can't see" in speaks[0].lower()
