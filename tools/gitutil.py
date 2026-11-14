"""Run git from any Python on this Mac, and fail loudly when it cannot run.

An x86_64 Python (the pi_pipeline venv under Rosetta) starts Apple's `git` wrapper, which can fail with an xcrun architecture error and no
output. A helper that returns only the output then reads that as an empty repository. This one tries the plain `git` first, then the
Command Line Tools binary, and raises when neither works (`check=False` returns "" instead, for a call that may legitimately fail).
"""
import subprocess

GIT_EXES = ("git", "/Library/Developer/CommandLineTools/usr/bin/git")


def git(*args, cwd=None, check=True):
    err = ""
    for exe in GIT_EXES:
        try:
            r = subprocess.run([exe, *args], cwd=cwd, capture_output=True, text=True)
        except OSError as e:
            err = str(e)
            continue
        if r.returncode == 0:
            return r.stdout
        err = (r.stderr or "").strip()[:200]
    if check:
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")
    return ""
