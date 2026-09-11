import json

from pi_pipeline.link.trace import TracingLink, load_trace, replay


class FakeLink:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return f"ok:{cmd}"

    def read_line(self):
        return ""

    def connect(self):
        return True

    def close(self):
        self.closed = True


def test_tracing_link_logs_every_send(tmp_path):
    path = tmp_path / "trace.jsonl"
    t = [0.0]
    lk = FakeLink()
    tl = TracingLink(lk, str(path), clock=lambda: t[0])
    t[0] = 1.0
    assert tl.send("kstr") == "ok:kstr"
    t[0] = 2.5
    tl.send("kwkF")
    tl.close()

    entries = load_trace(str(path))
    assert [e["cmd"] for e in entries] == ["kstr", "kwkF"]
    assert entries[0]["reply"] == "ok:kstr"
    assert entries[1]["t"] - entries[0]["t"] == 1.5
    assert lk.closed   # closing the trace also closes the wrapped link


def test_tracing_link_passthrough():
    lk = FakeLink()
    tl = TracingLink(lk, "/dev/null")
    assert tl.connect() is True
    assert tl.is_connected is False   # FakeLink has no is_connected -> getattr default
    tl.close()


def test_replay_dry_run_sends_nothing(tmp_path, capsys):
    path = tmp_path / "trace.jsonl"
    path.write_text('{"t": 0.0, "cmd": "kstr", "reply": ""}\n'
                    '{"t": 0.1, "cmd": "kup", "reply": ""}\n')
    n = replay(str(path), link=None, dry_run=True)
    assert n == 2
    out = capsys.readouterr().out
    assert "kstr" in out and "kup" in out and "dry" in out


def test_replay_sends_through_the_given_link(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text('{"t": 0.0, "cmd": "kstr", "reply": ""}\n'
                    '{"t": 0.0, "cmd": "d", "reply": ""}\n')
    lk = FakeLink()
    n = replay(str(path), link=lk, speed=1000.0)   # fast -- no real waiting in a test
    assert n == 2 and lk.sent == ["kstr", "d"]
