"""Runs the real-API livecheck under pytest -- SKIPS unless you ask for it.

Makes a few billed Anthropic calls. It used to run whenever a key was configured (the Mac's .env has one), so every full test run was billed (2026-10-07).
Now it needs G2_LIVECHECK=1 as well as a key:
    G2_LIVECHECK=1 pi_pipeline/.venv/bin/pytest pi_pipeline/tests/test_livecheck.py -s
"""
import os

import pytest

from pi_pipeline.config import settings
from pi_pipeline.voice.livecheck import run_livecheck

pytestmark = pytest.mark.skipif(
    os.environ.get("G2_LIVECHECK") != "1" or not settings.anthropic_api_key,
    reason="billed live-API check: run with G2_LIVECHECK=1 (and a key in .env)",
)


def test_voice_pipeline_live():
    r = run_livecheck(settings)
    print("\n" + "\n".join(r.lines))
    assert r.passed, "live voice check had failures (see output above)"
