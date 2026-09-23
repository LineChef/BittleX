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

    def poll_imu(self):
        out, self._lines = self._lines, []
        return out

    def send(self, cmd, **kw):
        self.sent = getattr(self, "sent", []) + [cmd]
        return ""


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


def _mcu(roll_deg, pitch_deg=0.0):
    return f"MCU:  0.00  0.00  1.00    0.0{pitch_deg:7.1f}{roll_deg:7.1f}"


def test_rotation_between_firmware_frames_reads_unstable_and_held_fires():
    """The stream has no gyro (parser returns 0), so before 2026-09-22
    imu_stable was always True and `held` could never fire. The rate is now
    the finite difference of consecutive frames."""
    clock = [0.0]
    link = _FakeLink([_mcu(30.0)])
    hub = SensorHub(link=link, cfg=SensorConfig(held_after_s=0.6), clock=lambda: clock[0])
    assert hub.sample()["imu_stable"] is True        # first frame: no rate yet
    for k, roll in enumerate((45.0, 60.0, 75.0, 60.0), start=1):
        clock[0] = 0.2 * k                           # 5 Hz, ~75 deg/s = 1.3 rad/s
        link._lines = [_mcu(roll)]
        out = hub.sample()
        assert out["imu_level"] is False and out["imu_stable"] is False
    assert out["held"] is True                       # unlevel + moving since t=0.2


def test_still_but_tilted_is_stable():
    clock = [0.0]
    link = _FakeLink([_mcu(40.0)])
    hub = SensorHub(link=link, cfg=SensorConfig(), clock=lambda: clock[0])
    hub.sample()
    clock[0] = 0.2
    link._lines = [_mcu(40.0)]
    out = hub.sample()
    assert out["imu_level"] is False and out["imu_stable"] is True and out["held"] is False


def test_start_and_stop_stream_send_the_real_tokens():
    link = _FakeLink([])
    hub = SensorHub(link=link)
    hub.start_stream()
    hub.stop_stream()
    assert link.sent == ["gP", "gp"]
