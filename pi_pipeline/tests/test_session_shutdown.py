"""tools/g2_session_shutdown.sh: the last step of a wrap-up: deploy what is waiting, rest G2 and stop the voice service, then shut the Pi down; it stops at the first step that fails. A throwaway git repo and stub commands stand in for the repo, the Pi and the deploy."""
import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "g2_session_shutdown.sh"


def _arch_prefix():
    """An Intel Python on an Apple-silicon Mac cannot run Apple's git shim (xcrun fails to load): `arch -arm64` runs it natively. Nothing is added where plain git works."""
    try:
        if subprocess.run(["git", "--version"], capture_output=True).returncode == 0:
            return []
    except OSError:
        pass
    return ["arch", "-arm64"]


PREFIX = _arch_prefix()


def git(repo, *a):
    return subprocess.run([*PREFIX, "git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *a], capture_output=True, text=True, check=True).stdout.strip()


def setup(tmp_path, pi_hash="head", answers=True, deploy_ok=True, stop_ok=True, dirty=False, docs_after=True, voice=None):
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "pi_pipeline").mkdir()
    shutil.copy(SCRIPT, repo / "tools" / "g2_session_shutdown.sh")
    git(repo, "init", "-q")
    (repo / "pi_pipeline" / "a.py").write_text("one\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "code one")
    code1 = git(repo, "rev-parse", "HEAD")
    (repo / "pi_pipeline" / "a.py").write_text("two\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "code two")
    code2 = git(repo, "rev-parse", "HEAD")
    if docs_after:
        (repo / "docs").mkdir()
        (repo / "docs" / "s.md").write_text("x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "docs")
    if dirty:
        (repo / "pi_pipeline" / "a.py").write_text("three\n")
    log = tmp_path / "calls.log"
    state = tmp_path / "down"
    pi = {"head": code2, "old": code1, "none": ""}[pi_hash]
    (tmp_path / "ssh").write_text(f"""#!/usr/bin/env bash
args="$*"
case "$args" in
  *"sudo shutdown"*) echo SHUTDOWN >> {log}; touch {state}; exit 0;;
  *deployed_commit*) echo "{pi}"; exit 0;;
  *is-active*) exit {0 if voice else 3};;
  *"touch "*shutdown_request*) echo ANNOUNCE >> {log}; [ "{voice}" = handled ] && touch {state}; exit 0;;
  *"test ! -e"*shutdown_request*) if [ "{voice}" = handled ]; then exit 0; fi; exit 1;;
  *"rm -f"*shutdown_request*) echo CLEARED >> {log}; exit 0;;
  *) if [ -e {state} ] || [ "{1 if answers else 0}" = 0 ]; then exit 255; fi; exit 0;;
esac
""")
    (tmp_path / "deploy").write_text(f"#!/usr/bin/env bash\necho DEPLOY >> {log}\nexit {0 if deploy_ok else 1}\n")
    (tmp_path / "stop").write_text(f"#!/usr/bin/env bash\necho STOP >> {log}\nexit {0 if stop_ok else 1}\n")
    for n in ("ssh", "deploy", "stop"):
        (tmp_path / n).chmod(0o755)
    env = dict(os.environ, G2_PI="u@pi", G2_SSH=str(tmp_path / "ssh"), G2_DEPLOY=str(tmp_path / "deploy"), G2_SAFE_STOP=str(tmp_path / "stop"), PATH=os.environ["PATH"])
    return repo, log, env


def run(repo, env, *args):
    env = dict(env)
    env["PATH"] = str(repo.parent / "fakebin") + os.pathsep + env["PATH"]
    (repo.parent / "fakebin").mkdir(exist_ok=True)
    (repo.parent / "fakebin" / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    (repo.parent / "fakebin" / "sleep").chmod(0o755)
    return subprocess.run([*PREFIX, "bash", str(repo / "tools" / "g2_session_shutdown.sh"), *args], capture_output=True, text=True, env=env, cwd=str(repo))


def calls(log):
    return log.read_text().split() if log.exists() else []


def test_waiting_code_is_deployed_before_the_pi_is_rested_and_shut_down(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="old")
    r = run(repo, env)
    assert r.returncode == 0 and calls(log) == ["DEPLOY", "STOP", "SHUTDOWN"], (r.stdout, r.stderr)               # in that order
    assert "no longer answers" in r.stdout


def test_a_docs_only_difference_needs_no_deploy(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="head")                                                               # the Pi has the last code commit; HEAD is a docs commit after it
    r = run(repo, env)
    assert r.returncode == 0 and calls(log) == ["STOP", "SHUTDOWN"] and "nothing to deploy" in r.stdout


def test_an_unknown_deployed_commit_deploys(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="none")
    assert run(repo, env).returncode == 0 and calls(log)[0] == "DEPLOY"


def test_a_failed_deploy_stops_everything_and_nothing_is_shut_down(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="old", deploy_ok=False)
    r = run(repo, env)
    assert r.returncode == 4 and calls(log) == ["DEPLOY"] and "NOT shut down" in r.stdout


def test_a_failed_safe_stop_stops_before_the_shutdown(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="head", stop_ok=False)
    r = run(repo, env)
    assert r.returncode == 5 and calls(log) == ["STOP"]


def test_code_not_committed_stops_it_and_nothing_is_sent(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="old", dirty=True)
    r = run(repo, env)
    assert r.returncode == 3 and calls(log) == [] and "not committed" in r.stdout


def test_a_pi_that_does_not_answer_is_could_not_verify_and_nothing_is_sent(tmp_path):
    repo, log, env = setup(tmp_path, answers=False)
    r = run(repo, env)
    assert r.returncode == 2 and calls(log) == [] and "could not verify" in r.stdout


def test_a_dry_run_sends_nothing(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="old")
    r = run(repo, env, "--dry-run")
    assert r.returncode == 0 and calls(log) == [] and r.stdout.count("(dry run) would run") == 3 and "nothing was sent" in r.stdout


def test_a_running_voice_service_is_asked_to_power_down_and_nothing_else_is_forced(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="head", voice="handled")
    r = run(repo, env)
    assert r.returncode == 0 and calls(log) == ["ANNOUNCE"] and "Powering down" in r.stdout and "no longer answers" in r.stdout   # he says it, rests and shuts down himself: no plain stop or shutdown from here


def test_a_voice_service_that_does_not_take_the_request_falls_back_to_the_plain_stop_and_shutdown(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="head", voice="ignored")
    r = run(repo, env)
    assert r.returncode == 0 and calls(log) == ["ANNOUNCE", "CLEARED", "STOP", "SHUTDOWN"] and "will not say anything" in r.stdout


def test_a_dry_run_names_the_announced_power_down_and_still_sends_nothing(tmp_path):
    repo, log, env = setup(tmp_path, pi_hash="old", voice="handled")
    r = run(repo, env, "--dry-run")
    assert r.returncode == 0 and calls(log) == [] and "ask the voice service to power down" in r.stdout
