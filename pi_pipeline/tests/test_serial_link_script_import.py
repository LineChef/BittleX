"""SerialLink must construct when its file is imported the way the by-path scripts do (run_gait.py puts pi_pipeline/ on sys.path and imports `link.serial_link`, so there is no package above it).
2026-11-18: a relative import in __init__ broke every g2walk / baseline run with 'attempted relative import beyond top-level package'."""
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]


def test_serial_link_constructs_when_imported_as_a_top_level_module():
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from link.serial_link import SerialLink\n"
            "SerialLink('/dev/null-not-opened')\n"
            "print('ok')\n") % str(PKG)
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr
