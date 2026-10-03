"""tools/check_docs.py: broken links, volatile facts in the wrong page, anchors and orphans."""
import importlib.util
import os

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
_spec = importlib.util.spec_from_file_location("check_docs_under_test", os.path.join(_TOOLS, "check_docs.py"))
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)


def _tree(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return str(tmp_path)


def _run(root):
    return cd.check(root, cd.md_files(root))


def test_clean_tree_has_no_errors(tmp_path):
    root = _tree(tmp_path, {
        "README.md": "See [status](docs/STATUS.md) and [guide](docs/guides/g.md#setup).\n",
        "docs/STATUS.md": "# Status\n",
        "docs/README.md": "[g](guides/g.md)\n",
        "docs/guides/g.md": "# G\n\n## Setup\n\nHello\n",
    })
    errors, warnings = _run(root)
    assert errors == [] and warnings == []


def test_broken_relative_link_is_an_error_but_urls_and_code_are_ignored(tmp_path):
    root = _tree(tmp_path, {
        "README.md": "[gone](docs/missing.md) and [web](https://example.com/x.md) and `[ex](nope.md)`\n\n```\n[fenced](also-nope.md)\n```\n",
    })
    errors, _ = _run(root)
    assert len(errors) == 1 and "docs/missing.md" in errors[0]


def test_hard_coded_test_counts_only_fail_in_pages_that_must_stay_current(tmp_path):
    root = _tree(tmp_path, {
        "README.md": "The suite has 679 tests.\n",
        "docs/guides/g.md": "all 599 passing\n",
        "docs/rl/some-log.md": "that night 659 tests passed\n",
        "docs/plan-detail/p.md": "22 new tests\n",
    })
    errors, _ = _run(root)
    flagged = sorted(e.split(":")[0] for e in errors)
    assert flagged == ["README.md", "docs/guides/g.md"]


def test_deployed_policy_name_is_allowed_only_on_status(tmp_path):
    root = _tree(tmp_path, {
        "pi_pipeline/gait/residual_policy.py": 'DEFAULT_POLICY = "Foo_Candidate9_ppo.onnx"\n',
        "docs/STATUS.md": "deployed: Foo_Candidate9\n",
        "docs/capabilities.md": "uses Foo_Candidate9 today\n",
        "docs/rl/log.md": "promoted Foo_Candidate9\n",
    })
    errors, _ = _run(root)
    assert [e.split(":")[0] for e in errors] == ["docs/capabilities.md"]


def test_missing_anchor_and_orphan_page_are_warnings_not_errors(tmp_path):
    root = _tree(tmp_path, {
        "docs/README.md": "[a](a.md#nope)\n",
        "docs/a.md": "# A\n",
        "docs/lonely.md": "# Nobody links here\n",
    })
    errors, warnings = _run(root)
    assert errors == []
    assert any("anchor #nope" in w for w in warnings) and any("orphan" in w and "lonely.md" in w for w in warnings)


def test_the_real_repo_docs_pass(tmp_path):
    """The docs in this repo are held to the same rules the pre-commit hook enforces."""
    root = os.path.abspath(os.path.join(_TOOLS, ".."))
    errors, _ = cd.check(root, cd.md_files(root))
    assert errors == [] and cd.backlog_errors(root) == []
