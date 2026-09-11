from pi_pipeline.link.check_serial import _firstmove, _JOINTS


class FakeLink:
    def __init__(self):
        self.sent = []

    def send(self, cmd, read_reply=True):
        self.sent.append(cmd)
        return ""


def test_firstmove_nudges_each_joint_and_returns_to_neutral(monkeypatch):
    lk = FakeLink()
    answers = iter(["", ""] * len(_JOINTS) + ["q"])   # nudge+confirm every joint, then stop
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _firstmove(lk, deg=15.0, walk_s=1.0)

    # every joint got a +15 then a 0 (neutral), in order, then a final rest
    moves = [c for c in lk.sent if c.startswith("m")]
    assert len(moves) == 2 * len(_JOINTS)
    for k, (name, idx) in enumerate(_JOINTS):
        assert moves[2 * k] == f"m{idx} 15"
        assert moves[2 * k + 1] == f"m{idx} 0"
    assert lk.sent[-1] == "d"   # always ends at rest


def test_firstmove_skip_leaves_that_joint_untouched(monkeypatch):
    lk = FakeLink()
    answers = iter(["s"] + ["q"])   # skip the first joint, quit before the second
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _firstmove(lk, deg=10.0, walk_s=1.0)
    assert not any(c.startswith("m0 ") for c in lk.sent)
    assert lk.sent == ["d"]


def test_firstmove_q_at_any_point_always_ends_at_rest(monkeypatch):
    lk = FakeLink()
    answers = iter(["", "q"])   # nudge the head, then quit before returning it to neutral
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _firstmove(lk, deg=15.0, walk_s=1.0)
    assert lk.sent[0] == "m0 15"
    assert lk.sent[-1] == "d"


def test_firstmove_declining_balance_and_walk_skips_them(monkeypatch):
    lk = FakeLink()
    answers = iter(["", ""] * len(_JOINTS) + ["q"])   # all joints ok, then decline kbalance
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _firstmove(lk, deg=15.0, walk_s=1.0)
    assert "kbalance" not in lk.sent and "kwkF" not in lk.sent


def test_firstmove_full_run_sends_balance_and_walk(monkeypatch):
    lk = FakeLink()
    answers = iter(["", ""] * len(_JOINTS) + ["", ""])   # all joints, balance, and walk
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _firstmove(lk, deg=15.0, walk_s=0.01)
    assert "kbalance" in lk.sent
    assert "kwkF" in lk.sent
    assert lk.sent[-1] == "d"   # auto-rest after the walk burst
