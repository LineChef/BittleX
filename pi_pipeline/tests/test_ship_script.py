"""tools/g2_ship.sh: the commit, push and deploy chain in one gated pass, with stub checks and deploy in a throwaway repo and remote."""
import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "g2_ship.sh"


def _arch_prefix():
    try:
        if subprocess.run(["git", "--version"], capture_output=True).returncode == 0:
            return []
    except OSError:
        pass
    return ["arch", "-arm64"]


PREFIX = _arch_prefix()
GIT = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false"]


def git(repo, *a):
    return subprocess.run([*PREFIX, "git", "-C", str(repo), *GIT, *a], capture_output=True, text=True, check=True).stdout.strip()


def setup(tmp_path, checks_ok=True, deploy_ok=True):
    remote = tmp_path / "remote.git"
    subprocess.run([*PREFIX, "git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "tools" / "g2_ship.sh")
    git(repo, "init", "-q", "-b", "development")
    git(repo, "remote", "add", "origin", str(remote))
    (repo / "pi_pipeline").mkdir(); (repo / "docs").mkdir()
    (repo / "pi_pipeline" / "a.py").write_text("one\n"); (repo / "docs" / "s.md").write_text("one\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "first"); git(repo, "push", "-q", "origin", "development")
    log = tmp_path / "calls.log"
    (tmp_path / "checks").write_text(f"#!/usr/bin/env bash\necho CHECKS \"$@\" >> {log}\nexit {0 if checks_ok else 1}\n")
    (tmp_path / "deploy").write_text(f"#!/usr/bin/env bash\necho DEPLOY >> {log}\nexit {0 if deploy_ok else 1}\n")
    for n in ("checks", "deploy"):
        (tmp_path / n).chmod(0o755)
    env = dict(os.environ, G2_CHECKS=str(tmp_path / "checks"), G2_DEPLOY=str(tmp_path / "deploy"), GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="user.email", GIT_CONFIG_VALUE_0="t@t",
               GIT_CONFIG_KEY_1="user.name", GIT_CONFIG_VALUE_1="t", GIT_CONFIG_KEY_2="core.hooksPath", GIT_CONFIG_VALUE_2="/dev/null")
    return repo, log, env


def ship(repo, env, *args):
    return subprocess.run([*PREFIX, "bash", str(repo / "tools" / "g2_ship.sh"), *args], capture_output=True, text=True, env=env, cwd=str(repo))


def calls(log):
    return log.read_text().split("\n")[:-1] if log.exists() else []


def test_code_is_committed_pushed_and_deployed_in_that_order(tmp_path):
    repo, log, env = setup(tmp_path)
    (repo / "pi_pipeline" / "a.py").write_text("two\n")
    r = ship(repo, env, "-m", "change the code", "pi_pipeline/a.py")
    assert r.returncode == 0 and "shipped" in r.stdout, (r.stdout, r.stderr)
    assert [c.split()[0] for c in calls(log)] == ["CHECKS", "DEPLOY"]
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/development")                      # pushed


def test_a_docs_only_commit_is_pushed_and_never_deployed(tmp_path):
    repo, log, env = setup(tmp_path)
    (repo / "docs" / "s.md").write_text("two\n")
    r = ship(repo, env, "-m", "docs", "--no-suite", "docs/s.md")
    assert r.returncode == 0 and "nothing under pi_pipeline/ changed" in r.stdout
    assert calls(log) == ["CHECKS --no-suite"]
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/development")


def test_failing_checks_commit_nothing(tmp_path):
    repo, log, env = setup(tmp_path, checks_ok=False)
    (repo / "pi_pipeline" / "a.py").write_text("two\n")
    head = git(repo, "rev-parse", "HEAD")
    r = ship(repo, env, "-m", "x", "pi_pipeline/a.py")
    assert r.returncode == 3 and git(repo, "rev-parse", "HEAD") == head and calls(log) == ["CHECKS"]


def test_a_failed_deploy_is_reported_after_the_push(tmp_path):
    repo, log, env = setup(tmp_path, deploy_ok=False)
    (repo / "pi_pipeline" / "a.py").write_text("two\n")
    r = ship(repo, env, "-m", "x", "pi_pipeline/a.py")
    assert r.returncode == 6 and "did not verify" in r.stdout
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/development")


def test_no_deploy_flag_skips_the_deploy(tmp_path):
    repo, log, env = setup(tmp_path)
    (repo / "pi_pipeline" / "a.py").write_text("two\n")
    r = ship(repo, env, "-m", "x", "--no-deploy", "pi_pipeline/a.py")
    assert r.returncode == 0 and [c.split()[0] for c in calls(log)] == ["CHECKS"]


def test_usage_errors_and_attribution_in_the_message_stop_before_anything_runs(tmp_path):
    repo, log, env = setup(tmp_path)
    (repo / "pi_pipeline" / "a.py").write_text("two\n")
    assert ship(repo, env, "pi_pipeline/a.py").returncode == 2                                           # no message
    assert ship(repo, env, "-m", "x", ".").returncode == 2                                               # not a folder
    assert ship(repo, env, "-m", "Co-" + "authored-by: someone", "pi_pipeline/a.py").returncode == 2        # an attribution line
    assert ship(repo, env, "-m", "per Claude's suggestion", "pi_pipeline/a.py").returncode == 2
    assert calls(log) == []
    git(repo, "checkout", "-q", "-b", "other")
    assert ship(repo, env, "-m", "x", "pi_pipeline/a.py").returncode == 2                                # not on development


def test_a_tests_only_commit_is_not_deployed(tmp_path):
    repo, log, env = setup(tmp_path)
    (repo / "pi_pipeline" / "tests").mkdir()
    (repo / "pi_pipeline" / "tests" / "test_a.py").write_text("x\n")
    r = ship(repo, env, "-m", "a test", "--no-suite", "pi_pipeline/tests/test_a.py")
    assert r.returncode == 0 and calls(log) == ["CHECKS --no-suite"] and "no deploy" in r.stdout
