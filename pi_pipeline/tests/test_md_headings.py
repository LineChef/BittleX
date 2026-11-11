import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import md_headings as h  # noqa: E402


def test_both_heading_forms_are_read_and_code_fences_front_matter_and_rules_are_not_headings():
    t = "---\naudience: x\n---\n\n# Title\n\nIntro.\n\nSection\n-------\n\n### Sub\n\n```\n## no\n```\n\n---\n\nAfter the rule.\n"
    assert [(lv, tx) for _i, lv, tx in h.parse_headings(t)] == [(1, "Title"), (2, "Section"), (3, "Sub")]


def test_h2_converts_to_a_title_over_dashes_and_a_list_like_title_is_escaped():
    new, n = h.h2_to_setext("# T\n\nText\n## 1. The exported policy\n\nMore\n\n## Plain\n")
    assert n == 2
    assert "\n1\\. The exported policy\n----" in new and "\nPlain\n-----" in new
    assert [(lv, h.unescape(tx)) for _i, lv, tx in h.parse_headings(new)] == [(1, "T"), (2, "1. The exported policy"), (2, "Plain")]
    assert h.h2_to_setext(new)[1] == 0                                   # converting again changes nothing


def test_the_renderer_turns_a_setext_title_into_an_h2_with_the_same_anchor():
    import md_render as r
    out = r.render("# T\n\nIntro.\n\n1\\. The first\n--------\n\nBody\n", slugify=lambda t: t.lower().replace(" ", "-").replace(".", ""))
    assert '<h2 id="1-the-first">1. The first</h2>' in out
