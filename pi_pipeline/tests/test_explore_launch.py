from pi_pipeline.explore_launch import command, launch


def test_the_command_stops_voice_first_and_always_restarts_it():
    c = command(600, python="/py", workdir="/w", user="u")
    s = " ".join(c)
    assert c[:4] == ["sudo", "-n", "systemd-run", "--unit=g2-explore"]
    assert "ExecStartPre=+/bin/systemctl stop g2-voice" in s and "ExecStopPost=+/bin/systemctl --no-block start g2-voice" in s
    assert s.endswith("-m pi_pipeline.explore_session --arm-on-start --exit-when-roam-ends --roam-s 600")
    assert "G2_FEATURES=" in s and "+explore" in s


def test_launch_skips_off_a_pi_and_when_a_session_is_already_running():
    calls = []
    assert launch(platform="darwin", run=lambda *a, **k: calls.append(a)) is False and calls == []

    class R:
        def __init__(self, rc): self.returncode = rc

    seq = [R(0)]
    assert launch(platform="linux", run=lambda *a, **k: seq.pop(0)) is False          # is-active succeeded -> already running
    ran = []

    def run(cmd, **k):
        ran.append(cmd)
        return R(3)                                                                   # not active

    assert launch(platform="linux", run=run) is True and ran[1][:3] == ["sudo", "-n", "systemd-run"]
    def boom(cmd, **k):
        raise OSError("no sudo")
    assert launch(platform="linux", run=boom) is False


def test_exploration_roams_by_default_and_stationary_is_the_opt_in():
    from pi_pipeline import explore_session as E
    assert E.parse_args([]).arm_on_start is True                       # default: roam at once (Tier 1)
    assert E.parse_args(["--stationary"]).arm_on_start is False        # opt-in: stay put until `arm`
    assert E.parse_args(["--stationary", "--arm-on-start"]).arm_on_start is True


def test_a_roam_bout_is_not_cut_off_by_the_behavior_layers_own_caps():
    """On 2026-10-07 G2 stopped walking after exactly 90 s of roaming: the mode controller's own cap on one armed bout ended it, and he fell back to looking around, sitting and resting."""
    import random
    from pi_pipeline import explore_session as E
    from pi_pipeline.behavior import BehaviorDriver, DriverInputs, Mode
    from pi_pipeline.personality.traits import BehaviorParams

    class Clk:
        t = 1000.0

        def __call__(self):
            return self.t

    def mode_after(seconds, limits):
        c = Clk()
        d = BehaviorDriver(BehaviorParams(), clock=c, rng=random.Random(0))
        c.t += 11
        if limits:
            E.apply_roam_limits(d, 600.0)
        d.tick(DriverInputs(arm_explore=True, frame=[]))
        end = c.t + seconds
        while c.t < end:
            d.tick(DriverInputs(frame=[]))
            c.t += 0.5
        return d.mode.mode

    assert mode_after(100.0, limits=False) is not Mode.EXPLORE          # the default: the bout is over after 90 s
    assert mode_after(100.0, limits=True) is Mode.EXPLORE               # with the session's limits it keeps roaming
    c = Clk()
    d = BehaviorDriver(BehaviorParams(), clock=c, rng=random.Random(0))
    E.apply_roam_limits(d, 0.0)
    assert d.mode.cfg.explore_max_secs > 1e6 and d.explorer.cfg.max_legs > 10 ** 6
