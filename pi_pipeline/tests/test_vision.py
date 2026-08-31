from pi_pipeline.vision.avoidance import Avoider, AvoiderConfig, AvoidanceAction
from pi_pipeline.vision.feed import Detection, MockDetectionFeed
from pi_pipeline.vision.scene import narrate, summarize


def det(area_side, bearing=0.5, conf=0.85, label="box"):
    s = area_side
    return Detection(label, conf, bearing - s / 2, 0.5 - s / 2, s, s)


def test_detection_derived_props():
    d = det(0.4, bearing=0.2)
    assert abs(d.area - 0.16) < 1e-9
    assert d.bearing == "left"
    assert det(0.2, bearing=0.5).bearing == "ahead"
    assert det(0.2, bearing=0.9).bearing == "right"


def test_avoider_debounce_then_turn():
    av = Avoider(AvoiderConfig(consecutive=2))
    near_ahead = [det(0.42)]  # area ~0.176: near, ahead, below stop_area
    assert av.decide(near_ahead) is AvoidanceAction.NONE      # frame 1: debouncing
    assert av.decide(near_ahead) in (AvoidanceAction.TURN_LEFT, AvoidanceAction.TURN_RIGHT)


def test_avoider_stop_skips_debounce():
    av = Avoider()
    assert av.decide([det(0.5)]) is AvoidanceAction.STOP  # area 0.25 >= stop_area, immediate


def test_avoider_backup_preempts_cooldown():
    av = Avoider(AvoiderConfig(consecutive=1, cooldown_frames=5))
    av.decide([det(0.42)])                 # -> a turn, starts cooldown
    got = av.decide([det(0.7)])            # area 0.49 >= backup_area, must preempt
    assert got is AvoidanceAction.BACK_UP


def test_avoider_clear_view_is_none():
    av = Avoider()
    assert av.decide([]) is AvoidanceAction.NONE
    assert av.decide([det(0.05)]) is AvoidanceAction.NONE  # tiny box, far


def test_approaching_scenario_escalates():
    frames = MockDetectionFeed.approaching(steps=16)
    seen = [Avoider().decide(f) for f in frames]  # fresh avoider each step? no -> one avoider
    av = Avoider()
    actions = [av.decide(f) for f in frames]
    assert AvoidanceAction.NONE in actions[:5]
    assert AvoidanceAction.BACK_UP in actions[-3:]


def test_summarize_and_narrate():
    frame = [det(0.5, bearing=0.85, label="person"), det(0.2, bearing=0.1, label="chair")]
    text = summarize(frame)
    assert "person" in text and "chair" in text and "on my right" in text
    spoken = narrate(frame, ask=lambda prompt: "There's a person to my right.")
    assert spoken == "There's a person to my right."
    assert summarize([]) == "Nothing notable in view."
