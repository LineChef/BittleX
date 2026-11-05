"""A goal session inside the voice service (goals/inprocess.py, user 2026-11-05): the request channel, the session wrapper, the borrowed parts and the `g2goal run` side."""
import json
import threading
import time
import types

import pytest

from pi_pipeline.explore_session import SharedParts
from pi_pipeline.goals import inprocess as ip


@pytest.fixture(autouse=True)
def _paths(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_GOAL_REQUEST", str(tmp_path / "request.json"))
    monkeypatch.setenv("G2_GOAL_SESSION_LOG", str(tmp_path / "session.log"))
    monkeypatch.setenv("G2_GOAL_RUNNING", str(tmp_path / "running"))
    monkeypatch.setenv("G2_GOALS", str(tmp_path / "goals.json"))
    monkeypatch.delenv("G2_GOAL_INPROCESS", raising=False)


class FakeLink:
    def __init__(self):
        self.sent = []

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return ""


def shared(**over):
    parts = dict(link=FakeLink(), camera=object(), tts=None)
    parts.update(over)
    return SharedParts(**parts)


# ---- ready

def test_ready_needs_a_link_a_camera_and_the_switch_on(monkeypatch):
    assert ip.ready(shared()) == (True, "")
    assert ip.ready(shared(link=None)) == (False, "no serial link")
    assert ip.ready(shared(camera=None))[0] is False and ip.ready(None)[0] is False
    monkeypatch.setenv("G2_GOAL_INPROCESS", "0")
    assert ip.ready(shared()) == (False, "G2_GOAL_INPROCESS is off")


# ---- the request channel

def test_a_request_is_read_once_and_a_stale_one_is_ignored():
    assert ip.pending_request() is None
    ip.request("ball_punt")
    assert ip.pending_request() == "ball_punt"
    assert ip.pending_request(now=time.time() + ip.STALE_REQUEST_S + 5) is None          # nobody is waiting for it any more
    ip.clear_request()
    assert ip.pending_request() is None


def test_the_watcher_hands_the_goals_start_phrase_to_the_voice_loop():
    got = threading.Event()
    heard = []
    stop = threading.Event()
    ip.watch(lambda phrase: (heard.append(phrase), got.set()), interval=0.05, stop=stop)
    ip.request("ball_punt")
    assert got.wait(3.0)
    stop.set()
    assert heard == ["ball goal"] and ip.pending_request() is None                          # taken: the request file is gone
    assert ip.start_phrase("walls") is None and ip.start_phrase("nothing") is None          # a standing goal has no start phrase


def test_the_voice_loop_takes_a_poked_command_as_if_it_had_been_said():
    from pi_pipeline.tests.test_wake_handover import _Rec, _wake

    class Quiet(_Rec):                                 # hears nothing at all: only the poke can end the wait
        def PartialResult(self):
            return json.dumps({"partial": ""})
    w, _holder = _wake()
    w._Recognizer, w._pending = Quiet, None
    w.poke("ball goal")
    w.wait()
    assert w.take_pending() == "ball goal" and w.take_pending() is None


# ---- the session wrapper

class _Session:
    def __init__(self, goal, approach, **kw):
        self.kw = kw
        _Session.seen = {"approach": approach, "exploring_during": None}

    def run(self):
        self.kw["say"]("attempt 1 of 10")
        _Session.seen["exploring_during"] = _Session.sh.exploring.is_set()
        _Session.seen["marker_during"] = __import__("os").path.exists(ip.running_path())
        return {"session": "abc", "goal": "ball_punt", "why": "attempts", "attempts": 3, "successes": 2, "minutes": 1.5, "lessons_saved": 0, "settings_now": {"x": 1}}


def test_a_session_runs_with_the_services_parts_and_leaves_them_as_it_found_them(monkeypatch):
    sh = shared()
    _Session.sh = sh
    monkeypatch.setattr("pi_pipeline.goals.runner.GoalSession", _Session)
    monkeypatch.setattr("pi_pipeline.goals.approach.make", lambda name, **kw: types.SimpleNamespace(name=name, **kw))
    summary = ip.run_goal_inprocess(sh, "ball_punt")
    assert summary["why"] == "attempts" and summary["attempts"] == 3 and "settings_now" not in summary
    assert _Session.seen["approach"].shared is sh                                          # the approach was built on the service's parts
    assert _Session.seen["exploring_during"] is True and _Session.seen["marker_during"] is True
    assert not sh.exploring.is_set() and not __import__("os").path.exists(ip.running_path())       # the guard stands back in and the deploy may go ahead
    text = open(ip.log_path()).read()
    assert "== START ball_punt ==" in text and "attempt 1 of 10" in text and "== END " in text


def test_a_session_that_crashes_rests_g2_and_still_ends_its_log(monkeypatch):
    sh = shared()

    class Boom:
        def __init__(self, *a, **k):
            pass

        def run(self):
            raise RuntimeError("camera gone")
    monkeypatch.setattr("pi_pipeline.goals.runner.GoalSession", Boom)
    monkeypatch.setattr("pi_pipeline.goals.approach.make", lambda name, **kw: object())
    summary = ip.run_goal_inprocess(sh, "ball_punt")
    assert summary["why"].startswith("error") and "krest" in sh.link.sent
    assert not sh.exploring.is_set() and "== END " in open(ip.log_path()).read()


def test_a_goal_that_is_not_a_task_is_refused_without_touching_the_robot():
    sh = shared()
    assert ip.run_goal_inprocess(sh, "walls")["why"] == "not a task goal" and sh.link.sent == []


# ---- the borrowed parts (BallPunt)

def test_ball_punt_borrows_the_services_link_camera_and_imu_and_hands_them_back(monkeypatch):
    from pi_pipeline.behavior import ball_chase as bc
    from pi_pipeline.goals.ball_punt import BallPunt

    released = []
    consumer = FakeLink()
    fan = types.SimpleNamespace(consumer=lambda: consumer, release=released.append)
    cam = object()
    sh = shared(fan=fan, camera=cam)
    made = {}
    monkeypatch.setattr(bc, "_SnapshotCamera", lambda raw: made.setdefault("cam", types.SimpleNamespace(raw=raw, premeter=lambda **k: None)))
    monkeypatch.setattr(bc, "_stand_if_lying", lambda link: made.setdefault("stood", link))
    walker = types.SimpleNamespace(stopped=False, stop=lambda rest=False: made.setdefault("walker_stopped", True))
    monkeypatch.setattr(bc, "SerialRobot", lambda link, **k: types.SimpleNamespace(link=link, _walker=walker, claw_pose=lambda *a: None))
    monkeypatch.setattr(bc, "PictureSaver", lambda path: "saver")
    monkeypatch.setattr("pi_pipeline.goals.walls.make_wall_check", lambda: None)
    monkeypatch.setattr("pi_pipeline.behavior.chase_pace.book_for_now", lambda: "pace")
    monkeypatch.setattr("pi_pipeline.link.serial_link.SerialLink", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not open the port itself")))
    monkeypatch.setattr("threading.Timer", lambda *a, **k: types.SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(time, "sleep", lambda s: None)

    b = BallPunt(shared=sh)
    b.open()
    assert b._link is consumer and made["cam"].raw is cam and made["stood"] is consumer and b.robot.link is consumer       # no second port, the service's camera
    b.close()
    assert "krest" in consumer.sent and released == [consumer] and made.get("walker_stopped")                              # rested; the IMU stream handed back; the walk stopped
    assert sh.link.sent == []                                                                                               # nothing sent on a link of its own


# ---- `g2goal run` side

def _service(monkeypatch, tmp_path, lines):
    """A voice service that, a moment after the request, writes `lines` to the session log."""
    monkeypatch.setattr(ip, "service_active", lambda *a, **k: True)

    def serve():
        for _ in range(100):
            if ip.pending_request():
                break
            time.sleep(0.01)
        for line in lines:
            time.sleep(0.02)
            ip.log_line(line)
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return t


def test_delegate_follows_the_service_until_the_session_ends(monkeypatch, tmp_path):
    _service(monkeypatch, tmp_path, ["== START ball_punt ==", "attempt 1 of 10 (#25)", '== END {"why": "attempts", "attempts": 2, "successes": 1} =='])
    out = []
    res = ip.delegate("ball_punt", say=out.append, sleep=lambda s: time.sleep(0.02), start_wait_s=5)
    assert res == {"why": "attempts", "attempts": 2, "successes": 1}
    assert any("attempt 1 of 10" in l for l in out)


def test_delegate_returns_none_when_the_service_cannot_take_it(monkeypatch):
    monkeypatch.setattr(ip, "service_active", lambda *a, **k: False)
    assert ip.delegate("ball_punt", say=lambda m: None) is None                               # not running: the old stop-and-run way
    monkeypatch.setattr(ip, "service_active", lambda *a, **k: True)
    monkeypatch.setenv("G2_GOAL_INPROCESS", "0")
    assert ip.delegate("ball_punt", say=lambda m: None) is None                               # switched off


def test_delegate_gives_up_when_nothing_picks_the_request_up_and_clears_it(monkeypatch):
    monkeypatch.setattr(ip, "service_active", lambda *a, **k: True)
    t = [0.0]
    res = ip.delegate("ball_punt", say=lambda m: None, start_wait_s=5, sleep=lambda s: t.__setitem__(0, t[0] + 3), clock=lambda: t[0])
    assert res is None and ip.pending_request() is None


def test_delegate_reports_a_handover_when_the_service_fell_back_to_the_old_way(monkeypatch, tmp_path):
    _service(monkeypatch, tmp_path, ["== HANDOVER (no camera in this service) =="])
    res = ip.delegate("ball_punt", say=lambda m: None, sleep=lambda s: time.sleep(0.02), start_wait_s=5)
    assert res == {"goal": "ball_punt", "why": "handover"}


def test_the_run_command_asks_the_service_first_and_only_falls_back_without_one(monkeypatch):
    from pi_pipeline.goals import __main__ as cli
    calls = []
    monkeypatch.setattr(cli, "_run_standalone", lambda g, a: calls.append("standalone"))
    monkeypatch.setattr(ip, "delegate", lambda gid, **k: (calls.append("delegate"), {"why": "attempts"})[1])
    cli.main(["run", "ball_punt"])
    assert calls == ["delegate"]                                                              # the service took it: nothing else ran
    calls.clear()
    monkeypatch.setattr(ip, "delegate", lambda gid, **k: (calls.append("delegate"), None)[1])
    cli.main(["run", "ball_punt"])
    assert calls == ["delegate", "standalone"]
    calls.clear()
    cli.main(["run", "ball_punt", "--standalone"])
    assert calls == ["standalone"]                                                            # --standalone never asks
