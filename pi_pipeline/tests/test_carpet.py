from pi_pipeline.gait.carpet import CarpetAction, CarpetConfig, CarpetDetector


def _det(**cfg):
    t = [0.0]
    d = CarpetDetector(CarpetConfig(**cfg), clock=lambda: t[0])
    return d, t


def _run(d, t, cmd, meas, secs, dt=0.1):
    for _ in range(int(secs / dt)):
        t[0] += dt
        a = d.update(cmd, meas)
    return a


def test_good_efficiency_stays_normal():
    d, t = _det()
    a = _run(d, t, 0.10, 0.095, 5.0)          # ~95% efficient
    assert a is CarpetAction.NORMAL


def test_moderate_slip_boosts_the_command():
    d, t = _det(boost_below=0.72, carpet_below=0.45, enter_s=1.5)
    a = _run(d, t, 0.10, 0.060, 3.0)          # 60% efficient
    assert a is CarpetAction.BOOST_CMD
    assert d.cmd_with_boost(0.10) > 0.10
    assert d.cmd_with_boost(-0.10) < -0.10   # sign-preserving
    assert d.cmd_with_boost(0.0) == 0.0      # not applied to a stand


def test_bad_slip_recommends_the_carpet_gait():
    d, t = _det(carpet_below=0.45, enter_s=1.5)
    a = _run(d, t, 0.10, 0.030, 3.0)          # 30% efficient
    assert a is CarpetAction.CARPET_GAIT


def test_needs_sustained_shortfall_before_acting():
    d, t = _det(enter_s=2.0)
    a = _run(d, t, 0.10, 0.03, 1.0)           # only 1 s of slip
    assert a is CarpetAction.NORMAL


def test_severity_de_escalates_then_hysteresis_to_normal():
    d, t = _det(enter_s=1.0, clear_s=3.0)
    _run(d, t, 0.10, 0.03, 2.0)               # 30% -> CARPET_GAIT
    assert d.action is CarpetAction.CARPET_GAIT
    _run(d, t, 0.10, 0.055, 3.0)              # 55%: still bad but not carpet-bad -> BOOST_CMD
    assert d.action is CarpetAction.BOOST_CMD
    _run(d, t, 0.10, 0.085, 1.0)              # recovered but < clear_s -> still BOOST_CMD
    assert d.action is CarpetAction.BOOST_CMD
    _run(d, t, 0.10, 0.095, 3.5)              # sustained good -> NORMAL
    assert d.action is CarpetAction.NORMAL


def test_ignores_ticks_below_min_cmd():
    d, t = _det(min_cmd=0.04)
    a = _run(d, t, 0.01, 0.0, 5.0)            # basically standing / turning
    assert a is CarpetAction.NORMAL
    assert "no forward command" in d.last_reason
