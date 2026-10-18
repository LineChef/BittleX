"""tools/build_docs_bundle.py: routes, link rewriting and navigation order (pure functions; no git, no network)."""
import importlib.util
import os

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
spec = importlib.util.spec_from_file_location("build_docs_bundle", os.path.join(ROOT, "tools", "build_docs_bundle.py"))
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


@pytest.mark.parametrize("path,route", [
    ("docs/README.md", ""),
    ("docs/STATUS.md", "STATUS"),
    ("docs/guides/cheatsheet.md", "guides/cheatsheet"),
    ("docs/guides/README.md", "guides"),
    ("docs/planned/ai-head/README.md", "planned/ai-head"),
    ("blueprints/README.md", "blueprints"),
    ("docs/hardware/build-logs/i2s-audio-build-log.md", "hardware/build-logs/i2s-audio-build-log"),
    ("pi_pipeline/voice/README.md", "code/pi_pipeline/voice"),
    ("pi_pipeline/README.md", "code/pi_pipeline"),
    ("tools/README.md", "code/tools"),
    ("README.md", "about"),
    ("pi_pipeline/tests/README.md", None),
    ("rl_training/opencat-gym/trained/notes.md", None),
])
def test_route_for(path, route):
    assert B.route_for(path) == route


def test_real_walk_data_csvs_are_not_pages_but_readmes_are():
    assert B.is_page("docs/rl/real-walk-data/2026-10-10/README.md")
    assert not B.is_page("docs/rl/real-walk-data/2026-10-10/notes.md")


PAGES = {"docs/guides/cheatsheet.md": "guides/cheatsheet", "docs/README.md": "", "docs/guides/README.md": "guides",
         "pi_pipeline/voice/README.md": "code/pi_pipeline/voice"}
ASSETS = {"docs/guides/operating-g2-quick-guide.pdf"}


def rw(text, src="docs/rl/README.md"):
    warnings = []
    out = B.rewrite_links(text, src, PAGES, ASSETS, "/docs", "/docs/_assets", "https://example.org/r", warnings)
    return out, warnings


def test_page_links_become_routes_and_keep_anchors():
    out, w = rw("[a](../guides/cheatsheet.md#setup) and [b](../README.md) and [c](../guides/)")
    assert "(/docs/guides/cheatsheet#setup)" in out and "(/docs)" in out and "(/docs/guides)" in out and not w


def test_asset_code_and_external_links():
    out, w = rw("[pdf](../guides/operating-g2-quick-guide.pdf) [code](../../pi_pipeline/voice/README.md) "
                "[src](../../tools/g2_aliases.sh) [web](https://example.com/x) [here](#top)")
    assert "(/docs/_assets/docs/guides/operating-g2-quick-guide.pdf)" in out
    assert "(/docs/code/pi_pipeline/voice)" in out
    assert "(https://example.org/r/blob/{branch}/tools/g2_aliases.sh)" in out
    assert "(https://example.com/x)" in out and "(#top)" in out and not w


def test_links_inside_code_fences_are_left_alone_and_missing_targets_warn():
    out, w = rw("```\n[a](../guides/cheatsheet.md)\n```\n[gone](../nope.md)")
    assert "(../guides/cheatsheet.md)" in out
    assert w and "nope.md" in w[0]


def test_slug_matches_github_style():
    assert B.slug("1. Setup and `g2`") == "1-setup-and-g2"
    assert B.slug("Stop and safety") == "stop-and-safety"


def test_title_summary_and_headings():
    md = "# The title\n\nFirst paragraph with a [link](x.md) and `code`.\n\n## Part one\n### Sub\n```\n## not a heading\n```\n"
    assert B.title_of(md, "x") == "The title"
    assert B.summary_of(md) == "First paragraph with a link and code."
    assert [h["text"] for h in B.headings_of(md)] == ["Part one", "Sub"]
