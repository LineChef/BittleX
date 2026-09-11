import os

from pi_pipeline.bringup import _load_progress, _run_interactive, _save_progress, _steps


def test_steps_have_unique_ids_and_the_ordered_sections():
    steps = _steps()
    ids = [s.id for s in steps]
    assert len(ids) == len(set(ids))
    sections = list(dict.fromkeys(s.section for s in steps))   # first-seen order
    assert sections == [
        "Assembly & mechanical", "Serial link", "Voice",
        "RL sim-to-real", "Vision on the robot", "Integration",
    ]


def test_no_movement_step_auto_runs():
    """Anything that could move a joint is `manual_cmd` (shown, never executed
    by the runbook itself) -- `cmd` (auto-runnable) is reserved for read-only/
    passive commands, never a raw serial `send`."""
    for s in _steps():
        if s.cmd:
            assert "send" not in s.cmd, (s.id, s.cmd)


def test_progress_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_STATE_DIR", str(tmp_path))
    assert _load_progress() == set()
    _save_progress({"1", "2"})
    assert _load_progress() == {"1", "2"}


def test_interactive_enter_marks_done_and_q_saves_and_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_STATE_DIR", str(tmp_path))
    steps = _steps()[:3]
    answers = iter(["", "", "q"])   # do step 1, do step 2, quit before step 3
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _run_interactive(steps, set())
    assert _load_progress() == {steps[0].id, steps[1].id}


def test_interactive_skip_does_not_mark_done(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_STATE_DIR", str(tmp_path))
    steps = _steps()[:2]
    answers = iter(["s", "q"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _run_interactive(steps, set())
    assert _load_progress() == set()


def test_interactive_r_runs_the_command_then_still_needs_a_done_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_STATE_DIR", str(tmp_path))
    ran = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: ran.append(cmd))
    steps = [s for s in _steps() if s.cmd][:1]
    answers = iter(["r", "", "q"])   # run it, then check it done, then quit (no more steps anyway)
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _run_interactive(steps, set())
    assert ran and ran[0] == steps[0].cmd
    assert _load_progress() == {steps[0].id}


# ------------------------------------------- stay-on-the-stand rule
def test_step_12_is_split_into_stand_and_floor():
    ids = [s.id for s in _steps()]
    assert "12a" in ids and "12b" in ids and "12" not in ids
    by_id = {s.id: s for s in _steps()}
    assert "STAND" in by_id["12a"].title.upper()
    assert "FLOOR" in by_id["12b"].title.upper()


def test_12b_confirm_gate_blocks_on_no(tmp_path, monkeypatch, capsys):
    from pi_pipeline.bringup import _run_interactive

    monkeypatch.setenv("G2_STATE_DIR", str(tmp_path))
    steps = [s for s in _steps() if s.id in ("12a", "12b")]
    answers = iter(["", "n"])   # do 12a, then decline the floor-test confirm
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _run_interactive(steps, set())
    assert _load_progress() == {"12a"}   # never got past the confirm to do 12b
    assert "go back to step 12a" in capsys.readouterr().out


def test_12b_confirm_gate_proceeds_on_yes(tmp_path, monkeypatch):
    from pi_pipeline.bringup import _run_interactive

    monkeypatch.setenv("G2_STATE_DIR", str(tmp_path))
    steps = [s for s in _steps() if s.id in ("12a", "12b")]
    answers = iter(["", "y", ""])   # do 12a, confirm the floor test, do 12b
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    _run_interactive(steps, set())
    assert _load_progress() == {"12a", "12b"}
