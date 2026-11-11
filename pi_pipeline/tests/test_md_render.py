import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import md_render as r  # noqa: E402


def test_titles_become_h4_and_the_rest_a_paragraph_in_lists_and_paragraphs():
    h = r.render("# T\n\nIntro.\n\nStatus: fine here.\n\n- Orientation: G2 stays up. More.\n- Plain item\n  - Child: yes\n")
    assert "<h4>Status</h4><p>fine here.</p>" in h
    assert "<li><h4>Orientation</h4><p>G2 stays up. More.</p></li>" in h
    assert "<li>Plain item<ul><li><h4>Child</h4><p>yes</p></li></ul></li>" in h
    assert "class=" not in h and "<strong>" not in h


def test_a_colon_inside_a_sentence_code_or_a_link_is_not_a_title():
    h = r.render("- See `a: b` for the details\n- A long sentence that ends before the colon. Then: more\n- [a link](x.md): after\n- https://example.com: not a title\n")
    assert "<h4>" not in h


def test_headings_carry_the_given_anchor_ids_and_the_article_carries_its_metadata():
    h = r.render("# Page\n\n## The `X` part\n", section="guides", audience="builder", kind="guide", slugify=lambda t: "custom-" + t.split()[0].lower())
    assert '<article data-section="guides" data-audience="builder" data-kind="guide">' in h
    assert '<h2 id="custom-the">' in h


def test_callouts_quotes_code_numbered_lists_links_and_escaping():
    h = r.render("> [!WARNING]\n> Careful.\n\n> plain\n\n1. one: a\n2. two\n\n```bash\necho \"<hi>\"\n```\n\nSee [x](y.md) and `<b>` and *em* and **bold**.\n")
    assert '<aside data-callout="warning"><h4>Warning</h4><p>Careful.</p></aside>' in h
    assert "<blockquote><p>plain</p></blockquote>" in h
    assert "<ol><li><h4>one</h4><p>a</p></li><li>two</li></ol>" in h
    assert '<pre data-lang="bash"><code>echo &quot;&lt;hi&gt;&quot;</code></pre>' in h
    assert '<a href="y.md">x</a>' in h and "<code>&lt;b&gt;</code>" in h and "<em>em</em>" in h and "<strong>bold</strong>" in h


def test_raw_html_in_the_markdown_is_escaped_never_passed_through():
    h = r.render("<script>alert(1)</script> text\n")
    assert "<script>" not in h and "&lt;script&gt;" in h
