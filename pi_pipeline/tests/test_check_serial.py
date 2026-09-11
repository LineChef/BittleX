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


# --------------------------------------------------------------- allmoves
from pi_pipeline.link.check_serial import _all_moves, _allmoves


def test_all_moves_covers_every_catalogue_deduped():
    moves = _all_moves()
    tokens = [t for _n, t, _k in moves]
    assert len(tokens) == len(set(tokens))          # no token sent twice
    kinds = {k for _n, _t, k in moves}
    assert kinds == {"skill", "gesture", "sleep", "carpet", "recovery"}
    # the recovery keyframes are last, and never covered by the other catalogues
    assert [k for _n, _t, k in moves[-3:]] == ["recovery"] * 3
    assert ("self-right", "krc", "recovery") in moves
    assert ("roll-from-supine", "krl", "recovery") in moves
    assert ("drop-recover", "kdropRec", "recovery") in moves


def test_allmoves_sends_every_token_and_logs_voltage(monkeypatch):
    lk = FakeLink()

    def fake_send(cmd, read_reply=True):
        lk.sent.append(cmd)
        return "12.1V" if cmd == "P" else ""

    lk.send = fake_send
    monkeypatch.setattr("builtins.input", lambda *_: "")   # accept the recovery confirm
    _allmoves(lk, hold=0.0, recovery_hold=0.0, skip_recovery=False,
             announce_s=0.0, bell=False)

    expected_tokens = [t for _n, t, _k in _all_moves()]
    sent_moves = [c for c in lk.sent if c != "P" and c != "d"]
    assert sent_moves == expected_tokens
    assert lk.sent[0] == "P"                        # idle baseline read before any move
    assert lk.sent[-1] == "d"                       # always ends at rest
    # one baseline read plus a voltage read after every move
    assert lk.sent.count("P") == len(expected_tokens) + 1


def test_allmoves_skip_recovery_omits_those_three():
    lk = FakeLink()
    _allmoves(lk, hold=0.0, recovery_hold=0.0, skip_recovery=True,
             announce_s=0.0, bell=False)
    assert "krc" not in lk.sent and "krl" not in lk.sent and "kdropRec" not in lk.sent
    assert lk.sent[-1] == "d"


def test_allmoves_q_at_the_recovery_confirm_stops_before_it(monkeypatch):
    lk = FakeLink()
    monkeypatch.setattr("builtins.input", lambda *_: "q")
    _allmoves(lk, hold=0.0, recovery_hold=0.0, skip_recovery=False,
             announce_s=0.0, bell=False)
    assert "krc" not in lk.sent
    assert lk.sent[-1] == "d"


def test_allmoves_announces_each_move_numbered_and_current(monkeypatch, capsys):
    lk = FakeLink()
    monkeypatch.setattr("builtins.input", lambda *_: "")   # accept the recovery confirm
    _allmoves(lk, hold=0.0, recovery_hold=0.0, skip_recovery=False,
             announce_s=0.0, bell=False)
    out = capsys.readouterr().out
    total = len(_all_moves())
    # every move gets an unambiguous, numbered "which one is this" header
    assert f"[1/{total}]" in out
    assert f"[{total}/{total}]" in out
    first_name = _all_moves()[0][0]
    assert first_name in out


def test_allmoves_skip_recovery_numbers_only_the_moves_actually_run(capsys):
    lk = FakeLink()
    _allmoves(lk, hold=0.0, recovery_hold=0.0, skip_recovery=True,
             announce_s=0.0, bell=False)
    out = capsys.readouterr().out
    expected_total = len(_all_moves()) - 3   # the 3 recovery keyframes never ran
    assert f"[1/{expected_total}]" in out
    assert f"[{expected_total}/{expected_total}]" in out
    assert f"/{len(_all_moves())}]" not in out   # never counts against the full total


def test_allmoves_bell_and_lead_time_are_controllable(monkeypatch, capsys):
    lk = FakeLink()
    monkeypatch.setattr("builtins.input", lambda *_: "")
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    _allmoves(lk, hold=0.0, recovery_hold=0.0, skip_recovery=True,
             announce_s=2.0, bell=True)
    out = capsys.readouterr().out
    assert "\a" in out                    # bell fired
    assert 2.0 in slept                   # the announce lead-time pause happened
