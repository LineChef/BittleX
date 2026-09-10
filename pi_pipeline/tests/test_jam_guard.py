from pi_pipeline.gait.jam_guard import JamAction, JamGuard, JamGuardConfig

# front-leg joints are idx 0..3; a "cmd" vector and a "fbk" vector that lags it
# by `err` degrees on `n` of the front joints simulates a foot pressed on a wall.
CMD = [40.0, -50.0, 40.0, -50.0, 30.0, -40.0, 30.0, -40.0]


def _fbk(err, n):
    v = list(CMD)
    for i in range(n):
        v[i] = CMD[i] - err          # servo can't reach target -> wide tracking error
    return v


def _guard(**cfg):
    t = [0.0]
    g = JamGuard(JamGuardConfig(**cfg), clock=lambda: t[0])
    return g, t


def _run(g, t, fbk, secs, *, forward=True, dt=0.05):
    a = g.action
    for _ in range(int(round(secs / dt))):
        t[0] += dt
        a = g.update(CMD, fbk, forward_active=forward)
    return a


def test_clean_tracking_stays_none():
    g, t = _guard()
    a = _run(g, t, _fbk(1.0, 4), 3.0)        # 1 deg error on all fronts -- fine
    assert a is JamAction.NONE


def test_sustained_front_divergence_backs_off():
    g, t = _guard(jam_deg=12.0, enter_s=0.4, backoff_s=1.0)
    a = _run(g, t, _fbk(20.0, 3), 0.8)      # 20 deg error on 3 front joints, 0.8s
    assert a is JamAction.BACK_OFF
    assert "back off" in g.last_reason


def test_needs_it_to_persist():
    g, t = _guard(enter_s=1.0)
    a = _run(g, t, _fbk(20.0, 3), 0.5)     # only 0.5 s of divergence
    assert a is JamAction.NONE


def test_one_strained_joint_is_not_a_jam():
    g, t = _guard(min_jammed_joints=2)
    a = _run(g, t, _fbk(25.0, 1), 3.0)     # only one front joint straining (leg-on-leg)
    assert a is JamAction.NONE


def test_not_a_jam_when_not_walking_forward():
    g, t = _guard()
    a = _run(g, t, _fbk(25.0, 4), 3.0, forward=False)
    assert a is JamAction.NONE
    assert "no forward command" in g.status


def test_full_sequence_backoff_then_turn_then_resume():
    g, t = _guard(enter_s=0.3, backoff_s=0.6, turn_s=0.8)
    a = _run(g, t, _fbk(20.0, 3), 0.5)     # jam confirmed
    assert a is JamAction.BACK_OFF
    a = _run(g, t, _fbk(20.0, 3), 0.7)     # backoff_s elapses -> turn (obstacle still there, ignored mid-maneuver)
    assert a is JamAction.TURN_AWAY
    assert "turning" in g.last_reason
    a = _run(g, t, _fbk(1.0, 4), 1.0)     # turn_s elapses, now clear -> resume
    assert a is JamAction.NONE
    assert "resume" in g.last_reason


def test_maneuver_runs_to_completion_even_if_the_jam_clears_early():
    g, t = _guard(enter_s=0.3, backoff_s=0.6, turn_s=0.8)
    _run(g, t, _fbk(20.0, 3), 0.5)                 # -> BACK_OFF
    a = _run(g, t, _fbk(1.0, 4), 0.3)            # jam gone immediately, still mid-backoff
    assert a is JamAction.BACK_OFF               # doesn't abort -- always turns
    a = _run(g, t, _fbk(1.0, 4), 0.4)
    assert a is JamAction.TURN_AWAY


def test_re_jam_right_after_resume_restarts_the_sequence():
    g, t = _guard(enter_s=0.3, backoff_s=0.5, turn_s=0.5)
    _run(g, t, _fbk(20.0, 3), 0.5)                 # BACK_OFF
    _run(g, t, _fbk(20.0, 3), 0.6)                 # -> TURN_AWAY
    a = _run(g, t, _fbk(1.0, 4), 0.6)            # -> resume (NONE)
    assert a is JamAction.NONE
    a = _run(g, t, _fbk(20.0, 3), 1.2)          # walked into another obstacle
    assert a is JamAction.BACK_OFF


def test_forward_command_dropped_mid_maneuver_releases():
    g, t = _guard(enter_s=0.3, backoff_s=2.0)
    _run(g, t, _fbk(20.0, 3), 0.5)                 # -> BACK_OFF
    assert g.action is JamAction.BACK_OFF
    a = _run(g, t, _fbk(20.0, 3), 0.5, forward=False)
    assert a is JamAction.NONE
    assert "released" in g.last_reason


def test_diag_event_shape():
    g, t = _guard(enter_s=0.3)
    _run(g, t, _fbk(20.0, 3), 0.6)
    args, kw = g.diag_event()
    assert args == ("gait", "WARN", "jam.detected")
    assert kw["action"] == "back_off" and "reason" in kw


def test_reset_clears_state():
    g, t = _guard(enter_s=0.3)
    _run(g, t, _fbk(20.0, 3), 0.6)
    assert g.action is JamAction.BACK_OFF
    g.reset()
    assert g.action is JamAction.NONE
    a = _run(g, t, _fbk(1.0, 4), 1.0)
    assert a is JamAction.NONE


def test_turn_token_picks_a_side():
    g, _ = _guard()
    assert g.turn_token(prefer_left=True) == JamGuardConfig().turn_left_token
    assert g.turn_token(prefer_left=False) == JamGuardConfig().turn_right_token
