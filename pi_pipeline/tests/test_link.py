import pytest

from pi_pipeline.link import opencat
from pi_pipeline.link.serial_link import SerialLink


def test_skill_command_builder():
    assert opencat.skill("wkF") == "kwkF"
    assert opencat.skill(" sit ") == "ksit"
    with pytest.raises(ValueError):
        opencat.skill("")


def test_move_joints_builder():
    assert opencat.move_joints([(0, 30), (8, -35)]) == "m0 30 8 -35"
    with pytest.raises(ValueError):
        opencat.move_joints([])


def test_beep_builder():
    assert opencat.beep([(12, 8), (14, 8)]) == "b12 8 14 8"


def test_is_safe_blocks_calibration():
    assert opencat.is_safe("kbalance")
    assert opencat.is_safe("d")
    assert not opencat.is_safe("c")
    assert not opencat.is_safe("c 0")
    assert not opencat.is_safe("cd")
    assert not opencat.is_safe("")


def test_serial_link_send_without_connection_is_safe():
    """No pyserial / no port: connect() fails, send() returns '' and never raises."""
    link = SerialLink("/dev/nonexistent-xyz", 115200, auto_reconnect=True)
    assert link.is_connected is False
    assert link.connect() is False
    assert link.send("kbalance") == ""     # must not raise
    link.close()


def test_serial_link_list_ports_returns_list():
    ports = SerialLink.list_ports()
    assert isinstance(ports, list)


# ------------------------------------------------------------------ IMU demux
class _FakeSerial:
    """Enough of pyserial.Serial for SerialLink's read paths."""

    def __init__(self, data=b""):
        self.buf = bytearray(data)
        self.is_open = True
        self.written = []

    @property
    def in_waiting(self):
        return len(self.buf)

    def read(self, n):
        out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out

    def write(self, b):
        self.written.append(b)

    def flush(self):
        pass

    def close(self):
        self.is_open = False


def _link_with(data, read_timeout=0.05):
    lk = SerialLink("/dev/null", read_timeout=read_timeout)
    lk._ser = _FakeSerial(data)
    return lk


IMU = b"MCU:  0.00  0.00  1.00    0.0   1.0   2.0\r\n"


def test_reply_read_skips_interleaved_imu_frames():
    lk = _link_with(IMU + IMU + b"8.1\r\n" + IMU)
    assert lk.send("P", settle=0.0) == "8.1"
    assert lk.poll_imu() == [IMU.decode().strip()] * 3


def test_poll_imu_is_non_blocking_and_keeps_partial_lines():
    lk = _link_with(IMU + b"MCU:  0.00  0.")
    import time
    t0 = time.monotonic()
    assert lk.poll_imu() == [IMU.decode().strip()]
    assert time.monotonic() - t0 < 0.01
    lk._ser.buf += b"00  1.00    0.0   3.0   4.0\n"
    assert lk.poll_imu() == ["MCU:  0.00  0.00  1.00    0.0   3.0   4.0"]


def test_poll_imu_drops_move_command_echoes():
    lk = _link_with(b"m\r\n" + IMU + b"m\r\n")
    assert lk.poll_imu() == [IMU.decode().strip()]
    assert lk.read_line() == ""                    # echoes consumed, not queued as replies


def test_read_line_times_out_on_its_own_deadline():
    import time
    lk = _link_with(b"", read_timeout=0.05)
    t0 = time.monotonic()
    assert lk.read_line() == ""
    assert time.monotonic() - t0 < 0.2
