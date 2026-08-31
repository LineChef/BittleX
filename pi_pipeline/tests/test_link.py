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
