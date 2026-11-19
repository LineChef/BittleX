"""tools/g2_skill_audit.py on made-up transcripts and skills."""
import importlib.util
import json
import os

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
_spec = importlib.util.spec_from_file_location("g2_skill_audit_under_test", os.path.join(_TOOLS, "g2_skill_audit.py"))
sa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sa)


def line(ts, name, **inp):
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})


def test_events_are_read_and_filtered_by_date(tmp_path):
    (tmp_path / "a.jsonl").write_text("\n".join([line("2026-10-01T10:00:00Z", "Skill", skill="ship"), line("2026-11-18T10:00:00Z", "Skill", skill="hw-session"), "junk",
                                                  line("2026-11-18T10:01:00Z", "Bash", command="cd x && bash tools/g2_sync.sh run --force all")]))
    ev = sa.read_events(tmp_path, "2026-11-01")
    assert [(e["kind"], e["name"] or e["text"][:6]) for e in ev] == [("skill", "hw-session"), ("bash", "cd x &")]


def test_skill_steps_never_run_and_script_candidates(tmp_path):
    (tmp_path / "ship").mkdir()
    (tmp_path / "ship" / "SKILL.md").write_text("Run `bash tools/g2_precommit_checks.sh` then `bash tools/g2_deploy_safe.sh`; also `g2groom`.")
    steps = sa.skill_steps(tmp_path)
    assert steps["ship"] == {"tools/g2_precommit_checks.sh", "tools/g2_deploy_safe.sh", "g2groom"}
    events = [{"kind": "skill", "name": "ship", "text": ""}, {"kind": "bash", "name": "", "text": "bash tools/g2_precommit_checks.sh"}] + \
             [{"kind": "bash", "name": "", "text": "cd r && ssh pi 'tail -n 5 x'"}] * 4 + [{"kind": "bash", "name": "", "text": "ls -la"}] * 5
    a = sa.audit(events, steps)
    assert a["invoked"] == {"ship": 1} and a["never_invoked"] == []
    assert a["steps_never_run"]["ship"] == ["g2groom", "tools/g2_deploy_safe.sh"]
    assert ("ssh pi", 4) in a["repeated"] and all("ls" not in s for s, _ in a["repeated"])        # plain shell chatter is not a candidate
    assert any("ssh pi" in ln for ln in sa.render(a))


def test_shape_names_the_routine():
    assert sa.shape("cd /x && bash tools/g2_sync.sh run --force all") == "tools/g2_sync.sh run"
    assert sa.shape("PYTHONPATH=. pi_pipeline/.venv/bin/python -m pi_pipeline.diag report") is not None
    assert sa.shape("ls tools") is None


def test_inline_scripts_and_pytest_get_readable_names():
    assert sa.shape("python3 - <<'EOF'\nprint(1)\nEOF") == "python inline script"
    assert sa.shape("pi_pipeline/.venv/bin/pytest -n auto") == "pytest"
    assert sa.shape("timeout 60 bash tools/g2_sync.sh run") == "tools/g2_sync.sh run"
