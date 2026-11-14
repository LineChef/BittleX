"""tools/gitutil.py: falls back to the second git binary, and raises (never returns an empty answer) when git cannot run."""
import importlib.util
import pathlib
import subprocess

import pytest

_spec = importlib.util.spec_from_file_location("gitutil", pathlib.Path(__file__).resolve().parents[2] / "tools" / "gitutil.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)


def _run_factory(results):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[0])
        r = results[len(calls) - 1]
        if isinstance(r, Exception):
            raise r
        return subprocess.CompletedProcess(cmd, r[0], r[1], r[2])
    return fake_run, calls


def test_first_git_that_works_is_used(monkeypatch):
    run, calls = _run_factory([(0, "ok\n", "")])
    monkeypatch.setattr(G.subprocess, "run", run)
    assert G.git("status") == "ok\n" and calls == ["git"]


def test_falls_back_when_the_wrapper_fails(monkeypatch):
    run, calls = _run_factory([(1, "", "xcrun: error: unable to load libxcrun"), (0, "real\n", "")])
    monkeypatch.setattr(G.subprocess, "run", run)
    assert G.git("status") == "real\n" and calls == list(G.GIT_EXES)


def test_raises_when_no_git_runs(monkeypatch):
    run, _ = _run_factory([(1, "", "xcrun: error"), OSError("no such file")])
    monkeypatch.setattr(G.subprocess, "run", run)
    with pytest.raises(RuntimeError):
        G.git("status")


def test_check_false_returns_empty(monkeypatch):
    run, _ = _run_factory([(1, "", "boom"), (1, "", "boom")])
    monkeypatch.setattr(G.subprocess, "run", run)
    assert G.git("rev-parse", check=False) == ""
