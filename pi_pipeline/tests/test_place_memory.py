import math

from pi_pipeline.behavior import PlaceMemory, PlaceMemoryConfig
from pi_pipeline.behavior.place_memory import _direction


def test_direction_bins():
    assert _direction(0.0) == "straight ahead"
    assert _direction(math.pi / 2) == "to the right"
    assert _direction(-math.pi / 2) == "to the left"
    assert _direction(math.pi) == "back the other way"


def test_pattern_emitted_only_after_min_sightings_and_once():
    pm = PlaceMemory(PlaceMemoryConfig(min_sightings=3))
    pm.observe("dog", -1.2)          # to the left
    pm.observe("dog", -1.1)
    assert pm.pending_notes() == []  # only 2
    pm.observe("dog", -1.3)          # 3rd -> a pattern
    notes = pm.pending_notes()
    assert len(notes) == 1 and "dog" in notes[0].lower() and "left" in notes[0].lower()
    pm.observe("dog", -1.2)          # 4th -> not re-emitted
    assert pm.pending_notes() == []


def test_same_label_different_directions_are_separate_patterns():
    pm = PlaceMemory(PlaceMemoryConfig(min_sightings=2))
    for _ in range(2):
        pm.observe("cat", 1.2)      # right
    for _ in range(2):
        pm.observe("cat", 0.0)     # ahead
    notes = pm.pending_notes()
    assert len(notes) == 2


def test_reset_clears_everything():
    pm = PlaceMemory(PlaceMemoryConfig(min_sightings=1))
    pm.observe("dog", 0.0)
    pm.pending_notes()
    pm.reset()
    pm.observe("dog", 0.0)
    assert len(pm.pending_notes()) == 1   # emits again after a reset


# --------------------------------------------- wired through driver + runtime
def test_driver_surfaces_place_notes_during_explore():
    import random
    from pi_pipeline.behavior import (
        BehaviorDriver, DriverInputs,
    )
    from pi_pipeline.behavior.explore import ExploreConfig
    from pi_pipeline.personality.traits import BehaviorParams
    from pi_pipeline.vision.feed import Detection

    class Clk:
        def __init__(self): self.t = 1000.0
        def __call__(self): return self.t
        def adv(self, dt): self.t += dt

    c = Clk()
    d = BehaviorDriver(BehaviorParams(approach_novelty=False, investigate_secs=0.1),
                       clock=c, rng=random.Random(0),
                       place_cfg=PlaceMemoryConfig(min_sightings=1))

    def mug():
        return [Detection("mug", 0.9, 0.05, 0.05, 0.5, 0.5)]   # big, off to one side

    seen_notes = list(d.tick(DriverInputs(arm_explore=True, frame=mug())).place_notes)
    for _ in range(40):
        c.adv(0.5)
        seen_notes += d.tick(DriverInputs(frame=mug())).place_notes
    assert any("mug" in n.lower() for n in seen_notes)


def test_runtime_forwards_place_notes_to_on_observation():
    import random
    from pi_pipeline.behavior import BehaviorDriver, BehaviorRuntime, DriverInputs
    from pi_pipeline.behavior.bindings import MockBindings
    from pi_pipeline.behavior.explore import ExploreConfig
    from pi_pipeline.personality.traits import BehaviorParams
    from pi_pipeline.vision.feed import Detection

    class Clk:
        def __init__(self): self.t = 1000.0
        def __call__(self): return self.t
        def adv(self, dt): self.t += dt

    c = Clk()
    d = BehaviorDriver(BehaviorParams(approach_novelty=False, investigate_secs=0.1),
                       clock=c, rng=random.Random(0),
                       place_cfg=PlaceMemoryConfig(min_sightings=1))
    facts = []
    rt = BehaviorRuntime(d, MockBindings(), hz=0, clock=c,
                         frame_source=lambda: [Detection("cat", 0.9, 0.05, 0.05, 0.5, 0.5)],
                         on_observation=facts.append)
    rt.post(arm_explore=True)
    for _ in range(40):
        c.adv(0.5)
        rt.tick()
    assert any("cat" in f.lower() for f in facts)
