"""turn_runs.yaw_rate_deg_s: the turn rate from a fw_skill_log CSV (yaw in radians, + = right)."""
import math

import pytest

from pi_pipeline.gait import turn_runs


def _csv(tmp_path, rate_deg_s, seconds=10.0, hz=5.0, start_deg=170.0):
    p = tmp_path / "t.csv"
    lines = ["# fw_skill_log  skill=kwkR seconds=10", "t,roll,pitch,yaw,gx,gy,gz,guard_state"]
    for i in range(int(seconds * hz) + 1):
        t = i / hz
        yaw = math.radians(((start_deg + rate_deg_s * t + 180) % 360) - 180)      # wrapped to +-180 like the IMU
        lines.append(f"{t:.4f},0.0,0.0,{yaw:.5f},0,0,0,ok")
    p.write_text("\n".join(lines))
    return str(p)


@pytest.mark.parametrize("rate", [-25.0, -8.0, 0.0, 12.0, 30.0])
def test_rate_is_recovered_through_the_wrap(tmp_path, rate):
    r = turn_runs.yaw_rate_deg_s(_csv(tmp_path, rate))
    assert r[0] == pytest.approx(rate, abs=0.2) and r[1] == pytest.approx(rate * 10.0, abs=2.0)


def test_too_few_rows_gives_none(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("t,roll,pitch,yaw,gx,gy,gz,guard_state\n0,0,0,0,0,0,0,ok\n")
    assert turn_runs.yaw_rate_deg_s(str(p)) is None
