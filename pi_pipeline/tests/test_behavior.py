from pi_pipeline.behavior import (
    ExploreAction,
    Explorer,
    Mode,
    ModeConfig,
    ModeController,
    Novelty,
    NoveltyConfig,
)
from pi_pipeline.personality import Personality
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.vision.feed import Detection


def det(area_side, bearing=0.5, label="mug", conf=0.9):
    s = area_side
    return Detection(label, conf, bearing - s / 2, 0.5 - s / 2, s, s)


# --- Novelty ---------------------------------------------------------------

def test_novelty_objects_fade():
    n = Novelty(NoveltyConfig(revisit_secs=100))
    assert n.is_novel_object("cat", now=0)          # never seen
    n.see_object("cat", now=0)
    assert not n.is_novel_object("cat", now=50)
    assert n.is_novel_object("cat", now=101)        # faded back to novel


def test_novelty_heading_staleness_and_stalest():
    n = Novelty(NoveltyConfig(revisit_secs=100, heading_bins=8))
    assert n.heading_staleness(0.0, now=0) == 1.0   # never visited
    n.see_heading(0.0, now=0)
    assert n.heading_staleness(0.05, now=0) == 0.0  # same bin, just visited
    assert 0.4 < n.heading_staleness(0.0, now=50) < 0.6
    stale = n.stalest_heading(now=10)               # some other direction
    assert n.heading_staleness(stale, now=10) == 1.0


# --- ModeController ------------------------------------------------------

class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def test_idle_to_explore_after_quiet():
    clk = Clock()
    p = BehaviorParams(idle_secs_before_explore=20)
    mc = ModeController(p, ModeConfig(settle_secs=3, explore_max_secs=60), clock=clk)
    assert mc.update() is Mode.IDLE
    clk.t = 19
    assert mc.update() is Mode.IDLE
    clk.t = 21
    assert mc.update() is Mode.EXPLORE


def test_conversation_preempts_and_resets():
    clk = Clock()
    mc = ModeController(BehaviorParams(idle_secs_before_explore=10),
                        ModeConfig(settle_secs=2), clock=clk)
    clk.t = 20
    assert mc.update() is Mode.EXPLORE
    mc.on_conversation_start()
    assert mc.update() is Mode.CONVERSE
    mc.on_conversation_end()
    assert mc.mode is Mode.IDLE
    clk.t = 21                                   # not yet past settle
    assert mc.update() is Mode.IDLE
    clk.t = 40                                   # past settle + idle window
    assert mc.update() is Mode.EXPLORE


def test_activity_stops_exploring():
    clk = Clock()
    mc = ModeController(BehaviorParams(idle_secs_before_explore=5), clock=clk)
    clk.t = 10
    assert mc.update() is Mode.EXPLORE
    mc.on_activity()
    assert mc.mode is Mode.IDLE


def test_explore_bout_times_out():
    clk = Clock()
    mc = ModeController(BehaviorParams(idle_secs_before_explore=5),
                        ModeConfig(explore_max_secs=30, settle_secs=1), clock=clk)
    clk.t = 10
    assert mc.update() is Mode.EXPLORE
    clk.t = 45
    assert mc.update() is Mode.IDLE


# --- Explorer ----------------------------------------------------------

def _explorer(spec="curiosity=0.9"):
    p = Personality.from_spec(spec).behavior_params()
    return Explorer(p, Novelty(NoveltyConfig(revisit_secs=100))), p


def test_explorer_wanders_when_nothing_new():
    ex, _ = _explorer("")                         # neutral: approach_novelty off
    d0 = ex.decide([], now=0.0)
    assert d0.action is ExploreAction.TURN        # first tick starts a leg
    d1 = ex.decide([], now=0.5)
    assert d1.action is ExploreAction.WANDER


def test_explorer_investigates_novelty_then_marks_it_seen():
    ex, p = _explorer("curiosity=0.4")            # mid: look, don't approach
    d = ex.decide([det(0.2, bearing=0.5, label="shoe")], now=0.0)
    assert d.action is ExploreAction.INVESTIGATE and d.target == "shoe"
    # still dwelling before investigate_secs elapses
    assert ex.decide([], now=p.investigate_secs * 0.5).action is ExploreAction.INVESTIGATE
    # after the dwell: the shoe is now "seen", so it's no longer novel
    after = ex.decide([det(0.2, label="shoe")], now=p.investigate_secs + 1.0)
    assert after.action is not ExploreAction.INVESTIGATE
    assert not ex.nov.is_novel_object("shoe", now=p.investigate_secs + 1.0)


def test_high_curiosity_approaches_offset_novelty():
    ex, _ = _explorer("curiosity=0.9")            # approach_novelty on
    d = ex.decide([det(0.1, bearing=0.9, label="box")], now=0.0)  # far-ish + off to the side
    assert d.action is ExploreAction.APPROACH
    assert d.turn > 0                             # bearing to the right


def test_centered_close_novelty_is_investigated_not_approached():
    ex, _ = _explorer("curiosity=0.9")
    d = ex.decide([det(0.5, bearing=0.5, label="ball")], now=0.0)  # big + dead ahead
    assert d.action is ExploreAction.INVESTIGATE


def test_explorer_ignores_specks_and_low_confidence():
    ex, _ = _explorer("curiosity=0.9")
    d = ex.decide([det(0.02, label="dust"), det(0.3, label="cat", conf=0.1)], now=0.0)
    assert d.action is ExploreAction.TURN        # nothing qualified -> wander
