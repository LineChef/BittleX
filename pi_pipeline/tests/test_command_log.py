"""link/command_log.py: the Pi's commands and the board's own lines (a voice command to the board shows up as an unprompted line)."""
from pi_pipeline.link import command_log as cl


def test_commands_and_unprompted_board_lines_are_logged(tmp_path, monkeypatch, capsys):
    p = tmp_path / "cmd.jsonl"
    monkeypatch.setenv("G2_COMMAND_LOG", str(p))
    monkeypatch.setenv("G2_ORIGIN", "user")
    cl.sent("ksit")
    cl.sent("i8 30 9 30")                                   # a joint stream: left out
    cl.heard("sit", 0.2)                                    # an echo right after a command
    cl.heard("sit", 9.0)                                    # nobody asked: the board did it on its own
    cl.heard("0.1, 0.2, 9.8", 9.0)                          # numbers only: left out
    rows = cl.read()
    assert [r["dir"] for r in rows] == ["pi", "board", "board"] and rows[0]["origin"] == "user"
    assert rows[1]["unprompted"] is False and rows[2]["unprompted"] is True
    assert cl.main(["--board"]) == 0 and "on its own" in capsys.readouterr().out


def test_the_serial_link_logs_what_it_sends_and_the_lines_nobody_asked_for(tmp_path, monkeypatch):
    p = tmp_path / "cmd.jsonl"
    monkeypatch.setenv("G2_COMMAND_LOG", str(p))
    from pi_pipeline.link.serial_link import SerialLink

    class FakeSerial:
        is_open = True

        def __init__(self):
            self.out = []

        def write(self, b):
            self.out.append(b.decode().strip())

        def flush(self):
            pass
    lk = SerialLink("/dev/null")
    lk._ser = FakeSerial()
    monkeypatch.setattr(SerialLink, "is_connected", property(lambda self: True))
    lk.send("kbalance", read_reply=False, settle=0.0)
    lines = iter(["sit", None])
    monkeypatch.setattr(lk, "_next_line", lambda block_until=None: next(lines))
    lk._last_sent_t -= 10.0                                                       # the board's line comes 10 s after the Pi's last command
    lk.poll_imu()
    rows = cl.read()
    assert rows[0]["cmd"] == "kbalance" and rows[-1] == {**rows[-1], "dir": "board", "line": "sit", "unprompted": True}
