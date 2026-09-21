"""SensorHub's IMU consumption -- specifically locking in the 2026-09-20 fix
where sensors.py had its own separate, unfixed parse_imu_line copy that
would NEVER successfully parse a real firmware line (wrong prefix
assumption), silently falling back to "assume level and stable" forever
rather than failing loudly. Now shares gait/imu_parse.py with run_gait.py.
"""
from pi_pipeline.app.sensors import SensorConfig, SensorHub


class _FakeLink:
    def __init__(self, lines):
        self._lines = list(lines)

    def read_line(self):
        return self._lines.pop(0) if self._lines else ""


def test_real_firmware_line_is_parsed_and_updates_level_and_stable():
    # A real MCU: line, tipped hard (roll=60deg > default level_deg=25) should
    # flip imu_level False -- proof the real line format actually parses now.
    link = _FakeLink(["MCU:  0.00  0.00  1.00    0.0   0.0  60.0"])
    hub = SensorHub(link=link, cfg=SensorConfig(stale_after_s=1.5), clock=lambda: 0.0)
    out = hub.sample()
    assert out["imu_level"] is False


def test_level_line_keeps_imu_level_true():
    link = _FakeLink(["MCU:  0.00  0.00  1.00    0.0   0.0   0.0"])
    hub = SensorHub(link=link, cfg=SensorConfig(), clock=lambda: 0.0)
    out = hub.sample()
    assert out["imu_level"] is True
    assert out["imu_stable"] is True


def test_no_data_falls_back_to_assume_level_after_stale_timeout():
    """The documented, intentional degrade-safe fallback -- distinct from the
    bug this test file guards against, where EVERY line silently failed to
    parse and this fallback fired permanently instead of occasionally."""
    link = _FakeLink([])   # no data at all
    clock = [0.0]
    hub = SensorHub(link=link, cfg=SensorConfig(stale_after_s=1.5), clock=lambda: clock[0])
    clock[0] = 2.0   # past stale_after_s with zero data ever received
    out = hub.sample()
    assert out["imu_level"] is True and out["imu_stable"] is True
