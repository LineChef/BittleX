from pi_pipeline.link import opencat
from pi_pipeline.link.recovery import (
    ACTION_COMMANDS,
    BodyState,
    RecoveryAction,
    RecoveryConfig,
    RecoveryFSM,
)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def feed(fsm, roll, pitch, n=1):
    """Feed the same (roll, pitch) n times; return the last action."""
    act = RecoveryAction.NONE
    for _ in range(n):
        act = fsm.update(roll, pitch)
    return act


def test_upright_never_acts():
    fsm = RecoveryFSM()
    for _ in range(20):
        assert fsm.update(0.05, -0.1) is RecoveryAction.NONE
    assert fsm.state is BodyState.UPRIGHT


def test_stumble_is_left_to_the_gait():
    """Tilted past a wobble but not fallen -> classified STUMBLING, action NONE."""
    fsm = RecoveryFSM()
    for _ in range(10):
        assert fsm.update(0.9, 0.2) is RecoveryAction.NONE
    assert fsm.state is BodyState.STUMBLING
    # ...and it recovers on its own
    assert fsm.update(0.1, 0.0) is RecoveryAction.NONE
    assert fsm.state is BodyState.UPRIGHT


def test_transient_fall_read_is_debounced():
    cfg = RecoveryConfig(fall_debounce=3)
    fsm = RecoveryFSM(cfg)
    assert fsm.update(1.5, 0.2) is RecoveryAction.NONE   # 1
    assert fsm.update(1.5, 0.2) is RecoveryAction.NONE   # 2
    assert fsm.update(0.1, 0.0) is RecoveryAction.NONE   # glitch cleared
    assert fsm.state is BodyState.UPRIGHT


def test_forward_fall_triggers_recover():
    cfg = RecoveryConfig(fall_debounce=3)
    fsm = RecoveryFSM(cfg)
    assert feed(fsm, 0.2, 1.6, n=2) is RecoveryAction.NONE
    assert fsm.update(0.2, 1.6) is RecoveryAction.RECOVER     # 3rd confirms
    assert fsm.state is BodyState.GETTING_UP


def test_side_fall_triggers_recover():
    fsm = RecoveryFSM(RecoveryConfig(fall_debounce=2))
    fsm.update(1.6, 0.1)
    assert fsm.update(1.6, 0.1) is RecoveryAction.RECOVER


def test_supine_fall_rolls_first():
    fsm = RecoveryFSM(RecoveryConfig(fall_debounce=2))
    fsm.update(0.1, 2.4)
    assert fsm.update(0.1, 2.4) is RecoveryAction.ROLL_THEN_RECOVER
    assert fsm.state is BodyState.GETTING_UP


def test_getup_success_then_settle():
    fsm = RecoveryFSM(RecoveryConfig(fall_debounce=1, stable_hold=3))
    assert fsm.update(0.2, 1.6) is RecoveryAction.RECOVER
    # skill runs; still tilted for a bit
    assert fsm.update(0.2, 1.6) is RecoveryAction.NONE
    # comes back upright and holds
    assert fsm.update(0.1, 0.1) is RecoveryAction.NONE    # stable 1
    assert fsm.update(0.1, 0.1) is RecoveryAction.NONE    # stable 2
    assert fsm.update(0.1, 0.1) is RecoveryAction.SETTLE  # stable 3 -> recovered
    assert fsm.state is BodyState.UPRIGHT
    assert fsm.update(0.1, 0.1) is RecoveryAction.NONE


def test_getup_retries_then_gives_up():
    clock = FakeClock()
    cfg = RecoveryConfig(fall_debounce=1, getup_timeout_s=5.0, max_attempts=3)
    fsm = RecoveryFSM(cfg, clock=clock)

    assert fsm.update(0.2, 1.7) is RecoveryAction.RECOVER   # attempt 1 starts
    # stays down past the timeout -> retry
    clock.advance(6.0)
    assert fsm.update(0.2, 1.7) is RecoveryAction.RECOVER   # attempt 2
    clock.advance(6.0)
    assert fsm.update(0.2, 1.7) is RecoveryAction.GIVE_UP   # attempt 3 fails -> give up
    # after giving up it stops acting
    assert fsm.update(0.2, 1.7) is RecoveryAction.NONE


def test_stable_streak_resets_if_it_wobbles_mid_getup():
    fsm = RecoveryFSM(RecoveryConfig(fall_debounce=1, stable_hold=3))
    fsm.update(0.2, 1.6)                                  # RECOVER
    assert fsm.update(0.1, 0.1) is RecoveryAction.NONE    # stable 1
    assert fsm.update(0.1, 0.1) is RecoveryAction.NONE    # stable 2
    assert fsm.update(0.9, 0.2) is RecoveryAction.NONE    # wobbled -> streak resets
    assert fsm.update(0.1, 0.1) is RecoveryAction.NONE    # stable 1 again
    assert fsm.update(0.1, 0.1) is RecoveryAction.NONE    # stable 2
    assert fsm.update(0.1, 0.1) is RecoveryAction.SETTLE  # stable 3


def test_action_commands_use_real_tokens():
    assert ACTION_COMMANDS[RecoveryAction.RECOVER] == [opencat.RECOVER]
    assert ACTION_COMMANDS[RecoveryAction.ROLL_THEN_RECOVER] == [opencat.ROLL_OVER, opencat.RECOVER]
    assert ACTION_COMMANDS[RecoveryAction.SETTLE] == [opencat.BALANCE]
    assert opencat.RECOVER == "krc" and opencat.ROLL_OVER == "krl"
    for cmds in ACTION_COMMANDS.values():
        for c in cmds:
            assert opencat.is_safe(c)


def test_reset_clears_state():
    fsm = RecoveryFSM(RecoveryConfig(fall_debounce=1))
    fsm.update(0.2, 1.7)
    assert fsm.state is BodyState.GETTING_UP
    fsm.reset()
    assert fsm.state is BodyState.UPRIGHT
    assert fsm.update(0.05, 0.05) is RecoveryAction.NONE
