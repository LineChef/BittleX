"""tools/eta.py reads the trainer's console table and the runners' log lines. These snapshots fail loudly if either format changes (so a format change cannot turn into silently wrong estimates)."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import eta  # noqa: E402

TABLE = """---------------------------------
| rollout/           |          |
|    ep_len_mean     | 466      |
| time/              |          |
|    fps             | {fps}    |
|    iterations      | 1        |
|    time_elapsed    | {el}     |
|    total_timesteps | {st}     |
"""


def write_log(path, rows):
    with open(path, "w") as f:
        for st, el in rows:
            f.write(TABLE.format(fps=1, el=el, st=st))


def test_reads_steps_and_elapsed(tmp_path):
    p = tmp_path / "x_console.log"
    write_log(p, [(1_000_000, 200), (2_000_000, 450)])
    assert eta.read_pairs(str(p)) == [(1_000_000, 200), (2_000_000, 450)]


def test_plan_refuses_without_history(tmp_path, capsys):
    assert eta.cmd_plan(3e6, None, str(tmp_path)) == 1
    assert "not enough history" in capsys.readouterr().out


def test_plan_uses_similar_finished_runs(tmp_path, capsys):
    for n, sec in (("a", 1200), ("b", 1300), ("c", 1250)):
        p = tmp_path / f"{n}_console.log"
        write_log(p, [(1_000_000, 400), (3_000_000, sec)])
        old = time.time() - 3600
        os.utime(p, (old, old))
    assert eta.cmd_plan(3e6, "stage", str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "basis: 3 finished runs" in out and "verdict" in out


def test_now_measures_recent_pace(tmp_path, capsys):
    p = tmp_path / "live_console.log"
    write_log(p, [(s * 500_000, s * 100) for s in range(1, 8)])        # 5000 steps/s
    assert eta.cmd_now(10e6, "final20m", str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "5000 steps/s" in out and "training done in about 22-" in out


def test_check_pairs_start_with_its_own_finish(tmp_path, capsys):
    (tmp_path / "phase_v9.log").write_text(
        "[v9 07:00 PM] v9_s1 START: lever, 3e6 steps, about 20 min, done about 07:20 PM\n"
        "[v9 07:30 PM] v9_s1 START: lever, 3e6 steps, about 20 min, done about 07:50 PM\n"
        "[v9 07:55 PM] v9_s1 DONE, scored in 3 min\n")
    assert eta.cmd_check(str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "took   25 min" in out and out.count("promised") == 1


def test_check_says_so_when_the_format_changed(tmp_path, capsys):
    (tmp_path / "phase_v9.log").write_text("something else entirely\n")
    assert eta.cmd_check(str(tmp_path)) == 1
    assert "format may have changed" in capsys.readouterr().out
