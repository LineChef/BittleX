"""Runs the real-API livecheck under pytest -- SKIPS with no key configured.

Makes a few billed Anthropic calls when a key is present. To run it:
    ANTHROPIC_API_KEY=... pi_pipeline/.venv/bin/pytest pi_pipeline/tests/test_livecheck.py -s
"""
import pytest

from pi_pipeline.config import settings
from pi_pipeline.voice.livecheck import run_livecheck

pytestmark = pytest.mark.skipif(
    not settings.anthropic_api_key,
    reason="no ANTHROPIC_API_KEY -- set it in .env to run the live voice check",
)


def test_voice_pipeline_live():
    r = run_livecheck(settings)
    print("\n" + "\n".join(r.lines))
    assert r.passed, "live voice check had failures (see output above)"
