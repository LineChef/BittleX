import os
import sys

_GAIT = os.path.join(os.path.dirname(__file__), "..", "gait")
sys.path.insert(0, os.path.abspath(_GAIT))
import fw_skill_log  # noqa: E402

LEVEL = "MCU:  0.00  0.00  1.00    0.0   1.0   2.0"
SIDE = "MCU:  0.00  0.00  1.00    0.0   0.0  90.0"


class _Link:
    def __init__(self, line):
        self.line, self.sent = line, []

    def send(self, cmd, **kw):
        self.sent.append(cmd)

    def poll_imu(self):
        return [self.line]


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.05)


def test_runs_skill_logs_imu_and_rests(tmp_path):
    lk, c = _Link(LEVEL), _Clock()
    log = tmp_path / "fw.csv"
    res = fw_skill_log.run_skill(lk, "kcarpetF", 2.0, str(log), sleep=c.sleep, clock=c)
    assert res["fell"] is False and res["ticks"] > 10
    assert lk.sent[:3] == ["gB", "kbalance", "gP"] and "kcarpetF" in lk.sent
    assert lk.sent[-3:] == ["gp", "kbalance", "d"]
    rows = log.read_text().splitlines()
    assert rows[1].startswith("t,roll,pitch,yaw") and len(rows) > 10


def test_aborts_and_rests_on_a_fall(tmp_path):
    lk, c = _Link(SIDE), _Clock()
    res = fw_skill_log.run_skill(lk, "kcarpetF", 10.0, None, sleep=c.sleep, clock=c)
    assert res["fell"] is True and c.t < 8.0
    assert lk.sent[-2:] == ["gp", "d"]
