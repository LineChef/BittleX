import math

from pi_pipeline.gait.stand_log import run, summarize


def test_summarize_finds_a_steady_stand_and_a_wobble():
    steady = [0.5 + 0.02 * ((i % 3) - 1) for i in range(60)]
    s = summarize(steady, steady)
    assert s["roll"][1] < 0.05 and s["roll"][2] < 0.1
    wobble = [3.0 * math.sin(2 * math.pi * 0.8 * i / 5.0) for i in range(60)]     # a 0.8 Hz swing, +/-3 degrees
    w = summarize(wobble, steady)
    assert w["roll"][1] > 1.5 and w["roll"][2] > 5 and abs(w["roll_hz"] - 0.8) < 0.1


def test_summarize_copes_with_too_few_samples():
    s = summarize([0.0], [0.0])
    assert s["roll"] is None and s["roll_hz"] is None


class FakeLink:
    def __init__(self):
        self.sent, self._i = [], 0

    def send(self, cmd, read_reply=True, settle=0.05):
        self.sent.append(cmd)
        return "Voltage: 7.80 V" if cmd == "P" else ""

    def drain(self, s=0.2):
        return ""

    def poll_imu(self):
        self._i += 1
        return ["ICM:  0.00  0.00  1.00    0.0    2.0    1.0"]


def test_run_sends_no_motion_commands_and_logs(tmp_path):
    t = [0.0]
    lk = FakeLink()
    log = tmp_path / "s.csv"
    lines = []
    windows = run(lk, 2.1 / 60 * 60 / 60, str(log), volt_every=1.0, sleep=lambda s: t.__setitem__(0, t[0] + 1.0),
                  clock=lambda: t[0], out=lines.append)
    assert set(lk.sent) <= {"gP", "gp", "P"}                       # only the IMU print on/off and the voltage query
    text = log.read_text()
    assert ",imu," in text and ",volt,,,,7.80" in text


def test_accel_tilt_from_gravity_alone():
    from pi_pipeline.gait.stand_log import _accel_g, accel_tilt_deg
    assert accel_tilt_deg(0.0, 0.0, 1.0) == (0.0, 0.0)
    r, p = accel_tilt_deg(0.0, 0.1736, 0.9848)          # ~10 degrees of roll
    assert abs(r - 10) < 0.1 and abs(p) < 0.01
    assert _accel_g("ICM:  0.01  0.17  0.98   12.3    1.0    2.0") == (0.01, 0.17, 0.98)
    assert _accel_g("hello") is None
    assert _accel_g("ICM:  0.20  0.17 10.4717640.5    1.1    0.9\t") == (0.2, 0.17, 10.47)     # columns run together
    assert _accel_g("ICM: -0.20 -0.17  9.81 3044.2    1.1    0.9") == (-0.2, -0.17, 9.81)


def test_balance_off_sends_gb_first_and_restores_gB_at_the_end(tmp_path):
    t = [0.0]
    lk = FakeLink()
    run(lk, 0.02, None, volt_every=1.0, balance="off", sleep=lambda s: t.__setitem__(0, t[0] + 0.5),
        clock=lambda: t[0], out=lambda *a: None)
    cmds = [c for c in lk.sent if c != "P"]
    assert cmds[0] == "gb" and cmds[-1] == "gB" and "gp" in cmds


def test_default_leaves_balance_alone():
    t = [0.0]
    lk = FakeLink()
    run(lk, 0.02, None, volt_every=1.0, sleep=lambda s: t.__setitem__(0, t[0] + 0.5), clock=lambda: t[0], out=lambda *a: None)
    assert "gb" not in lk.sent and "gB" not in lk.sent
