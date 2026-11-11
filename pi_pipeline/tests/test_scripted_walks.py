from pi_pipeline.telemetry.scripted_walks import ScriptedWalkLog


class FakeRun:
    def __init__(self, kind, extra):
        self.kind, self.extra, self.finished = kind, extra, None

    def finish(self, reason, **kw):
        self.finished = (reason, kw)


def make():
    runs = []

    def new_run(kind, *, extra=None, **_):
        r = FakeRun(kind, extra)
        runs.append(r)
        return r
    return ScriptedWalkLog(new_run=new_run), runs


def test_gait_opens_and_next_motion_command_ends_it():
    w, runs = make()
    w.note("kwkF")
    assert len(runs) == 1 and runs[0].kind == "scripted_walk" and runs[0].extra == {"token": "kwkF"}
    w.note("gP")                                   # not a motion command: the walk goes on
    assert runs[0].finished is None
    w.note("kbalance")
    assert runs[0].finished == ("ended_by:kbalance", {"token": "kwkF"})


def test_next_gait_ends_the_running_one_and_starts_another():
    w, runs = make()
    w.note("kwkF")
    w.note("kwkL")
    assert runs[0].finished[0] == "next:kwkL" and len(runs) == 2 and runs[1].extra == {"token": "kwkL"}
    w.note("d")
    assert runs[1].finished[0] == "ended_by:d"


def test_other_commands_without_a_gait_do_nothing():
    w, runs = make()
    for c in ("ksit", "krest", "gb", "i0 30", ""):
        w.note(c)
    assert runs == []


def test_a_failing_logger_never_raises():
    def boom(*a, **k):
        raise RuntimeError("no")
    w = ScriptedWalkLog(new_run=boom)
    w.note("kwkF")
    w.note("kbalance")
    w.close()
