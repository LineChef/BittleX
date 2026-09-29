from pi_pipeline.link.check_serial import _firstmove, _JOINTS, _burst, _feedback_check


class FakeLink:
    def __init__(self):
        self.sent = []
        self.drains = 0

    def send(self, cmd, read_reply=True):
        self.sent.append(cmd)
        return ""

    def drain(self, seconds=0.3):
        self.drains += 1
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


# ------------------------------------------------------------------ burst

def test_burst_sends_token_then_rests_in_one_connection(monkeypatch):
    lk = FakeLink()
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    _burst(lk, "kwkR", 1.5)
    assert lk.sent == ["kwkR", "d"]   # exactly two sends, no second connect()/reboot
    assert slept == [1.5]


# --------------------------------------------------------------- feedback

def test_feedback_check_reads_twice_around_one_prompt_same_connection(monkeypatch, capsys):
    lk = FakeLink()
    readings = iter(["28.0", "41.0"])   # different -- looks like real feedback
    lk.send = lambda cmd, read_reply=True: (lk.sent.append(cmd), next(readings))[1]
    monkeypatch.setattr("builtins.input", lambda *_: "")
    _feedback_check(lk)
    assert lk.sent == ["f", "f"]   # both reads in the one connection, no reboot between
    assert lk.drains == 2          # drained before each read
    out = capsys.readouterr().out
    assert "Different -- consistent with real position feedback." in out


def test_feedback_check_flags_unchanged_reading_as_likely_not_real(monkeypatch, capsys):
    lk = FakeLink()
    lk.send = lambda cmd, read_reply=True: (lk.sent.append(cmd), "28.0")[1]
    monkeypatch.setattr("builtins.input", lambda *_: "")
    _feedback_check(lk)
    out = capsys.readouterr().out
    assert "Same/unchanged" in out


# --------------------------------------------------------------- allmoves
from pi_pipeline.link.check_serial import _all_moves, _allmoves
from pi_pipeline.link import opencat


class OrderedFakeLink:
    """Like FakeLink, but keeps send/drain in one timeline so ordering
    between them can be asserted (real bug: a move's echoed reply, never
    read because moves are sent with read_reply=False, was bleeding into
    the *next* voltage read unless drained first -- see check_serial.py)."""

    def __init__(self):
        self.calls: list[tuple] = []

    def send(self, cmd, read_reply=True):
        self.calls.append(("send", cmd))
        return ""

    def drain(self, seconds=0.3):
        self.calls.append(("drain",))
        return ""


from pi_pipeline.link.check_serial import _read_voltage


class ScriptedLink:
    """Returns each of `replies` in order on successive send() calls,
    regardless of the command -- for exercising _read_voltage's retry loop
    in isolation from the rest of allmoves."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.drains = 0

    def send(self, cmd, read_reply=True):
        return self.replies.pop(0) if self.replies else ""

    def drain(self, seconds=0.3):
        self.drains += 1
        return ""


def test_read_voltage_retries_past_stray_lines_then_succeeds():
    # imuException debug line, then a stale-backlog fragment, then the real reading
    lk = ScriptedLink(["imuException: \t0", "k", "Voltage: 7.80 V"])
    assert _read_voltage(lk, attempts=4, drain_s=0.0) == "Voltage: 7.80 V"
    assert lk.drains == 3   # one drain immediately before each attempt


def test_read_voltage_gives_up_after_attempts_without_blocking_forever():
    lk = ScriptedLink(["k", "k", "k", "imuException: \t0", "Voltage: 7.80 V"])
    # only 4 attempts allowed; the real reading (5th) is never reached
    assert _read_voltage(lk, attempts=4, drain_s=0.0) == "imuException: \t0"
    assert lk.drains == 4


def test_allmoves_drains_before_every_voltage_read():
    lk = OrderedFakeLink()
    _allmoves(lk, hold=0.0, recovery_hold=0.0, skip_recovery=True, skip_gaits=True,
             announce_s=0.0, bell=False)
    voltage_sends = [i for i, c in enumerate(lk.calls)
                     if c == ("send", opencat.PRINT_VOLTAGE)]
    assert voltage_sends   # sanity: the baseline read plus one per move actually happened
    for i in voltage_sends:
        assert lk.calls[i - 1] == ("drain",), (
            f"voltage read at {i} not immediately preceded by a drain: "
            f"{lk.calls[max(0, i - 2):i + 1]}"
        )


def test_all_moves_covers_every_catalogue_deduped():
    moves = _all_moves()
    tokens = [t for _n, t, _k in moves]
    assert len(tokens) == len(set(tokens))          # no token sent twice
    kinds = {k for _n, _t, k in moves}
    assert kinds == {"gait", "skill", "gesture", "sleep", "carpet", "recovery"}
    # continuous locomotion skills (walk/trot/crawl) are "gait", not "skill",
    # so --skip-gaits can filter them as a group alongside carpet-walk
    assert ("walk_forward", "kwkF", "gait") in moves
    assert ("sit", "ksit", "skill") in moves
    # the recovery keyframes are last, and never covered by the other catalogues
    assert [k for _n, _t, k in moves[-3:]] == ["recovery"] * 3
    assert ("self-right", "krc", "recovery") in moves
    assert ("roll-from-supine", "krl", "recovery") in moves
    assert ("drop-recover", "kdropRec", "recovery") in moves


def test_allmoves_sends_every_token_and_logs_voltage(monkeypatch):
    lk = FakeLink()

    def fake_send(cmd, read_reply=True):
        lk.sent.append(cmd)
        return "Voltage: 12.10 V" if cmd == "P" else ""

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


def test_allmoves_skip_gaits_omits_gaits_and_carpet():
    lk = FakeLink()
    _allmoves(lk, hold=0.0, recovery_hold=0.0, skip_recovery=True, skip_gaits=True,
             announce_s=0.0, bell=False)
    gait_tokens = {t for _n, t, k in _all_moves() if k in ("gait", "carpet")}
    assert not (gait_tokens & set(lk.sent))
    assert "ksit" in lk.sent   # non-gait skills still run
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
