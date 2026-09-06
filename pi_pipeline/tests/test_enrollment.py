from pi_pipeline.behavior.enrollment import (
    Enrollment, EnrollmentConfig, EnrollAction, EnrollState, build_script,
    count_completed_sessions, new_session_dir, mark_session_done,
)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def adv(self, dt):
        self.t += dt


def _fsm(**cfg):
    c = Clock()
    return Enrollment(EnrollmentConfig(**cfg), clock=c), c


def _upd(fsm, c, **kw):
    kw.setdefault("person_present", True)
    kw.setdefault("face_quality", 1.0)
    kw.setdefault("good_frames_this_step", 999)
    return fsm.update(now=c.t, **kw)


def _run_step(fsm, c):
    """Advance through one CAPTURING step to its CAPTURE_ON of the next (or COMPLETE)."""
    for _ in range(400):
        c.adv(0.2)
        tk = _upd(fsm, c)
        if tk.action in (EnrollAction.CAPTURE_ON, EnrollAction.COMPLETE, EnrollAction.ABORT):
            return tk
    raise AssertionError("step did not advance")


def test_start_first_session_greets_with_plan():
    fsm, c = _fsm()
    tk = fsm.start("Alex", prior_sessions=0)
    assert tk.action is EnrollAction.SPEAK and fsm.state is EnrollState.GREETING
    assert tk.session_index == 1 and tk.sessions_left == 2   # 2 remain after this one
    assert "Alex" in tk.speak and "3 sets" in tk.speak


def test_start_last_session_phrasing():
    fsm, c = _fsm()
    tk = fsm.start("Sam", prior_sessions=2)
    assert tk.session_index == 3
    assert "finishes it" in tk.speak or "session 3 of 3" in tk.speak


def test_start_when_already_enrolled():
    fsm, c = _fsm()
    tk = fsm.start("Sam", prior_sessions=3)
    assert fsm.state is EnrollState.DONE
    assert "already" in tk.speak.lower()


def test_greeting_settles_then_starts_step_1():
    fsm, c = _fsm(greeting_settle_s=3.0)
    fsm.start("Alex", prior_sessions=0, now=c.t)
    c.adv(1.0)
    assert _upd(fsm, c).action is EnrollAction.NONE          # still settling
    c.adv(2.5)
    tk = _upd(fsm, c)
    assert tk.action is EnrollAction.CAPTURE_ON and fsm.state is EnrollState.CAPTURING
    assert tk.step_kind == build_script(1)[0].kind


def test_step_does_not_advance_before_min_frames_even_if_timed_in():
    fsm, c = _fsm(greeting_settle_s=0.0)
    fsm.start("Alex", prior_sessions=0, now=c.t)
    _upd(fsm, c)                                             # -> step 1 CAPTURE_ON
    c.adv(10.0)
    tk = _upd(fsm, c, good_frames_this_step=0)              # timed in, but no frames
    assert tk.action is EnrollAction.NONE and fsm.state is EnrollState.CAPTURING


def test_step_advances_when_timed_in_and_enough_frames():
    fsm, c = _fsm(greeting_settle_s=0.0)
    fsm.start("Alex", prior_sessions=0, now=c.t)
    _upd(fsm, c)
    c.adv(5.0)
    tk = _upd(fsm, c, good_frames_this_step=50)
    assert tk.action is EnrollAction.CAPTURE_ON             # moved to step 2
    assert tk.step_kind == build_script(1)[1].kind


def test_step_advances_on_max_step_timeout_without_frames():
    fsm, c = _fsm(greeting_settle_s=0.0, max_step_s=6.0)
    fsm.start("Alex", prior_sessions=0, now=c.t)
    _upd(fsm, c)
    c.adv(7.0)
    tk = _upd(fsm, c, good_frames_this_step=0)
    assert tk.action is EnrollAction.CAPTURE_ON             # forced on to step 2


def test_full_session_reaches_complete_with_remaining_count():
    fsm, c = _fsm(greeting_settle_s=0.0)
    fsm.start("Alex", prior_sessions=0, now=c.t)
    tk = _upd(fsm, c)                                       # step 1
    n = len(build_script(1))
    for _ in range(n):
        tk = _run_step(fsm, c)
    assert tk.action is EnrollAction.COMPLETE and fsm.state is EnrollState.DONE
    assert tk.sessions_left == 2 and "set 1" in tk.speak


def test_last_session_complete_says_ready_to_train():
    fsm, c = _fsm(greeting_settle_s=0.0)
    fsm.start("Alex", prior_sessions=2, now=c.t)
    _upd(fsm, c)
    tk = None
    for _ in range(len(build_script(3))):
        tk = _run_step(fsm, c)
    assert tk.action is EnrollAction.COMPLETE and tk.sessions_left == 0
    assert "train me" in tk.speak.lower()


def test_person_lost_pauses_then_resumes():
    fsm, c = _fsm(greeting_settle_s=0.0, person_lost_grace_s=2.0)
    fsm.start("Alex", prior_sessions=0, now=c.t)
    _upd(fsm, c)                                            # step 1 CAPTURE_ON
    c.adv(1.0)
    _upd(fsm, c, person_present=False)                      # marks _t_lost
    c.adv(3.0)                                              # now lost > grace (2.0)
    tk = _upd(fsm, c, person_present=False)
    assert fsm.state is EnrollState.PAUSED and "back in front" in tk.speak
    c.adv(1.0)
    tk = _upd(fsm, c, person_present=True)
    assert tk.action is EnrollAction.CAPTURE_ON and fsm.state is EnrollState.CAPTURING


def test_person_gone_too_long_aborts():
    fsm, c = _fsm(greeting_settle_s=0.0, abort_after_lost_s=10.0)
    fsm.start("Alex", prior_sessions=0, now=c.t)
    _upd(fsm, c)
    c.adv(1.0)
    for _ in range(60):
        c.adv(1.0)
        tk = _upd(fsm, c, person_present=False)
        if tk.action is EnrollAction.ABORT:
            break
    assert tk.action is EnrollAction.ABORT and fsm.state is EnrollState.ABORTED


def test_quality_nudge_fires_once():
    fsm, c = _fsm(greeting_settle_s=0.0, bad_quality_nudge_s=2.0)
    fsm.start("Alex", prior_sessions=0, now=c.t)
    _upd(fsm, c)
    c.adv(0.5); _upd(fsm, c, face_quality=0.1, good_frames_this_step=0)
    c.adv(2.5)
    tk = _upd(fsm, c, face_quality=0.1, good_frames_this_step=0)
    assert tk.action is EnrollAction.SPEAK and "closer" in tk.speak.lower()
    c.adv(2.0)
    tk = _upd(fsm, c, face_quality=0.1, good_frames_this_step=0)
    assert tk.action is EnrollAction.NONE                   # only nudges once per step


def test_cancel_aborts():
    fsm, c = _fsm(greeting_settle_s=0.0)
    fsm.start("Alex", prior_sessions=0, now=c.t)
    _upd(fsm, c)
    tk = fsm.cancel()
    assert tk.action is EnrollAction.ABORT and fsm.state is EnrollState.ABORTED


def test_scripts_differ_by_session():
    s1, s2, s3 = build_script(1), build_script(2), build_script(3)
    assert [x.kind for x in s1] != [x.kind for x in s2]
    assert any(x.kind == "tilt" for x in s2)
    assert all(s[-1].kind == "negative" for s in (s1, s2, s3))


def test_fs_helpers_count_completed_sessions(tmp_path):
    root = str(tmp_path)
    assert count_completed_sessions(root, "Alex") == 0
    d1 = new_session_dir(root, "Alex", 1)
    assert count_completed_sessions(root, "Alex") == 0     # not marked done yet
    mark_session_done(d1)
    new_session_dir(root, "Alex", 2)
    assert count_completed_sessions(root, "Alex") == 1
    mark_session_done(new_session_dir(root, "Alex", 2))
    assert count_completed_sessions(root, "Alex") == 2
