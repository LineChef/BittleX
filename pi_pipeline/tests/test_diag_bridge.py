import json
import random

import pytest

from pi_pipeline.diag.core import Diag
from pi_pipeline.behavior import BehaviorDriver, DriverInputs
from pi_pipeline.behavior import diag_bridge
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.vision.cliff_guard import CliffGuard, EdgeReading


class Clk:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


@pytest.fixture
def dg(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_LOG_DIR", str(tmp_path))
    d = Diag()
    monkeypatch.setattr(diag_bridge, "diag", d)
    d.start_session("behavior")
    yield d
    d.close()


def _events(d):
    return [json.loads(l) for l in (d.session_dir / "events.jsonl").read_text().splitlines() if l]


def test_mode_and_posture_transitions_become_diag_events(dg):
    p = BehaviorParams(idle_secs_before_explore=1e9, idle_sit_secs=20, idle_rest_secs=90)
    drv = BehaviorDriver(p, clock=(c := Clk()), rng=random.Random(0))

    diag_bridge.emit_tick(drv.tick(DriverInputs()))        # no transition yet
    c.adv(21)
    n = diag_bridge.emit_tick(drv.tick(DriverInputs()))    # active -> sit
    assert n == 1

    evs = _events(dg)
    pt = [e for e in evs if e["name"] == "posture.transition"]
    assert pt and pt[0]["detail"] == "active->sit"
    assert "because" in pt[0] and pt[0]["posture"] == "sit"


def test_cliff_reflex_is_a_warn_event(dg):
    p = BehaviorParams(idle_secs_before_explore=5)
    drv = BehaviorDriver(p, clock=(c := Clk()), rng=random.Random(0), cliff=CliffGuard())
    c.adv(6)
    edge = EdgeReading(present=True, dist_norm=0.15, bearing_norm=0.0, confidence=1.0)
    diag_bridge.emit_tick(drv.tick(DriverInputs(edge=edge, frame=[])))

    evs = _events(dg)
    cr = [e for e in evs if e["name"] == "cliff.reflex"]
    assert cr and cr[0]["lvl"] == "WARN"


def test_quiet_tick_emits_nothing(dg):
    drv = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                         clock=Clk(), rng=random.Random(0))
    drv.tick(DriverInputs())                               # settle the first transition
    before = len(_events(dg))
    for _ in range(5):
        diag_bridge.emit_tick(drv.tick(DriverInputs()))
    assert len(_events(dg)) == before                      # steady state is silent
