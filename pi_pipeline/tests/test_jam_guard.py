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


# ------------------------------------------------------------------ lag tolerance
def _swing(t):
    """A front-leg command sweeping ~200 deg/s, like the walk's fast phase."""
    import math
    a = 35.0 * math.sin(2 * math.pi * 1.0 * t)
    return [a, -a, -a, a, 30.0, -40.0, 30.0, -40.0]


def test_healthy_leg_lagging_the_command_is_not_a_jam():
    """With `i`, the servo trails the Pi's command by ~55 ms (firmware easing +
    oldest-wins backlog). Against the LATEST command that is 10+ deg of error on
    a fast swing -- it must not read as a jam."""
    g, t = _guard(enter_s=0.3)
    a = JamAction.NONE
    for k in range(160):                                   # 2 s at 80 Hz
        t[0] = k / 80
        fbk = _swing(t[0] - 0.055)                         # healthy, 55 ms late
        a = g.update(_swing(t[0]), fbk, forward_active=True)
        assert a is JamAction.NONE


def test_leg_pinned_by_an_obstacle_mid_walk_is_a_jam():
    """Realistic wall: two front joints follow their (lagged) command except they
    can't pass 0 deg -- divergence only on the part of the stride that pushes
    into the obstacle, which is exactly what the windowed per-joint mean catches."""
    g, t = _guard(enter_s=0.3)
    a = JamAction.NONE
    for k in range(160):
        t[0] = k / 80
        fbk = list(_swing(t[0] - 0.055))
        fbk[0] = min(fbk[0], 0.0)
        fbk[3] = min(fbk[3], 0.0)
        a = g.update(_swing(t[0]), fbk, forward_active=True)
        if a is JamAction.BACK_OFF:
            break
    assert a is JamAction.BACK_OFF


def test_ticks_without_a_feedback_read_only_record_the_command():
    g, t = _guard(enter_s=0.3)
    for k in range(160):
        t[0] = k / 80
        fbk = _fbk(20.0, 3) if k % 16 == 0 else None       # 5 Hz feedback reads
        a = g.update(CMD, fbk, forward_active=True)
        if a is JamAction.BACK_OFF:
            break
    assert a is JamAction.BACK_OFF
    g2, t2 = _guard()
    t2[0] = 0.1
    assert g2.update(CMD, None, forward_active=True) is JamAction.NONE
    assert "waiting" in g2.status
