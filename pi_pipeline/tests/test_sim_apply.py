import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "sim_train"))
import apply as ap  # noqa: E402


def test_apply_backs_up_sets_every_value_and_forgets_only_what_changed(tmp_path, monkeypatch):
    run = tmp_path / "run"; run.mkdir(); home = tmp_path / "home"; home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (run / "recommended_punt_settings.json").write_text(json.dumps({"winner": "sim#1", "recommended_settings": {"walk_aim_in": 5.0, "lost_looks": 3, "search_order": "claw_scan"}}))
    calls = []
    state = {"ball_punt": {ap.SCOPE: {"current": {"walk_aim_in": 4.0, "lost_looks": 3, "search_order": "back_turn"}}}}

    def fake_ssh(cmd, timeout=60):
        calls.append(cmd); return subprocess.CompletedProcess(cmd, 1 if "pgrep" in cmd else 0, "", "")      # pgrep finds nothing (exit 1): idle
    monkeypatch.setattr(ap, "ssh", fake_ssh)

    def fake_run(argv, **kw):                                   # scp: the backup of the goal state "arrives"
        if argv[0] == "scp" and argv[2].endswith("goal_state.json") and ":" in argv[2]:
            open(argv[3] + "goal_state.json", "w").write(json.dumps(state))
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(ap.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["apply.py", str(run)])
    assert ap.main() == 0
    sets = [c for c in calls if "punt_settings --set" in c]; forgets = [c for c in calls if "goals forget" in c]
    assert len(sets) == 3 and any("backups/sim_" in c for c in calls)
    assert [c.split("forget ball_punt ")[1].split()[0] for c in forgets] == ["walk_aim_in", "search_order"]          # lost_looks is unchanged: its real evidence stays
    assert os.path.exists(run / "APPLIED")


def test_nothing_is_applied_when_the_report_keeps_the_current_settings(tmp_path, monkeypatch):
    run = tmp_path; (run / "recommended_punt_settings.json").write_text(json.dumps({"winner": "none: the current real settings stay", "recommended_settings": {}}))
    monkeypatch.setattr(sys, "argv", ["apply.py", str(run)])
    assert ap.main() == 0 and not (run / "APPLIED").exists()


def test_an_unreachable_pi_means_try_again_later(tmp_path, monkeypatch):
    (tmp_path / "recommended_punt_settings.json").write_text(json.dumps({"winner": "sim#1", "recommended_settings": {"walk_aim_in": 5.0}}))
    monkeypatch.setattr(ap, "ssh", lambda cmd, timeout=60: subprocess.CompletedProcess(cmd, 255, "", "no route"))
    monkeypatch.setattr(sys, "argv", ["apply.py", str(tmp_path)])
    assert ap.main() == 2
