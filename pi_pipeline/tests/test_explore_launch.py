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
