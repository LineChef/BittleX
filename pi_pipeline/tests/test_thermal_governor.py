from pi_pipeline.behavior.thermal_governor import (
    GovernorState, ThermalGovernor, ThermalGovernorConfig,
)
from pi_pipeline.gait.thermal_guard import ThermalTier

G, A, R = ThermalTier.GREEN, ThermalTier.AMBER, ThermalTier.RED


def _gov(**cfg):
    t = [0.0]
    events = []
    g = ThermalGovernor(ThermalGovernorConfig(**cfg),
                        emit=lambda s, l, n, **kv: events.append((n, kv)),
                        clock=lambda: t[0])
    return g, t, events


def _run(g, t, tier, secs, dt=0.5):
    d = None
    for _ in range(int(round(secs / dt))):
        t[0] += dt
        d = g.update(tier)
    return d


def test_green_is_full_speed():
    g, t, _ = _gov()
    d = _run(g, t, G, 3.0)
    assert d.state is GovernorState.NORMAL
    assert d.speed_scale == 1.0 and not d.soften_gait and d.hold_pose is None


def test_amber_throttles_immediately():
    g, t, ev = _gov(throttle_speed_scale=0.55)
    d = g.update(A, now=1.0)
    assert d.state is GovernorState.THROTTLED
    assert d.speed_scale == 0.55 and d.soften_gait and d.avoid_uphill
    assert any(n == "thermal.governor_throttled" for n, _ in ev)


def test_red_holds_the_cooldown_pose():
    g, t, ev = _gov()
    d = g.update(R, now=1.0)
    assert d.state is GovernorState.COOLDOWN
    assert d.speed_scale == 0.0 and d.hold_pose is not None
    assert len(d.hold_pose) == 8
    assert any(n == "thermal.governor_cooldown" for n, _ in ev)


def test_escalation_green_to_red_is_immediate():
    g, t, _ = _gov()
    _run(g, t, G, 2.0)
    d = g.update(R)
    assert d.state is GovernorState.COOLDOWN


def test_amber_to_green_waits_out_deescalate_s():
    g, t, _ = _gov(deescalate_s=6.0)
    _run(g, t, A, 2.0)
    assert g.state is GovernorState.THROTTLED
    d = _run(g, t, G, 4.0)               # cooler, but < deescalate_s
    assert d.state is GovernorState.THROTTLED
    assert "cooling" in g.last_reason
    d = _run(g, t, G, 3.0)               # now > deescalate_s of cool
    assert d.state is GovernorState.NORMAL


def test_cooldown_holds_for_the_minimum_even_if_it_cools_fast():
    g, t, _ = _gov(cooldown_min_s=25.0, deescalate_s=3.0)
    g.update(R, now=1.0)
    assert g.state is GovernorState.COOLDOWN
    d = _run(g, t, G, 10.0)              # cooled to GREEN quickly, but < cooldown_min_s held
    assert d.state is GovernorState.COOLDOWN
    d = _run(g, t, G, 20.0)             # past cooldown_min_s and deescalate_s
    assert d.state is GovernorState.NORMAL


def test_cooldown_steps_down_to_throttled_not_straight_to_normal():
    g, t, _ = _gov(cooldown_min_s=5.0, deescalate_s=3.0)
    g.update(R, now=0.5)
    _run(g, t, A, 12.0)                  # RED -> (held) -> AMBER
    assert g.state is GovernorState.THROTTLED


def test_reheating_during_cooldown_resets_the_hold():
    g, t, _ = _gov(cooldown_min_s=8.0, deescalate_s=3.0)
    g.update(R, now=0.5)
    _run(g, t, G, 5.0)                   # cooling...
    _run(g, t, R, 1.0)                   # spiked back to RED
    d = _run(g, t, G, 6.0)             # 6 s cool again -- but the hold restarted
    assert d.state is GovernorState.COOLDOWN


def test_reset_returns_to_normal():
    g, t, _ = _gov()
    g.update(R, now=1.0)
    g.reset()
    assert g.state is GovernorState.NORMAL
    assert g.update(G, now=2.0).speed_scale == 1.0
