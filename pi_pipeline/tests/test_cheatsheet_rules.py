"""The cheat sheet stays a quick reference: tools/gen_cheatsheet_index.py's rules and A to Z index."""
import importlib.util
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
SPEC = importlib.util.spec_from_file_location("gen_cheatsheet_index", TOOLS / "gen_cheatsheet_index.py")
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


def _tree(tmp_path, main_rows, adv_rows=""):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "g2_aliases.sh").write_text("g2mic() { :; }\ng2rest() { :; }\nalias g2back='cd -'\n")
    (tmp_path / "docs" / "guides").mkdir(parents=True)
    head = "# Cheat sheet\n\n## Voice and mic\n\n| Command | Does |\n|---|---|\n"
    (tmp_path / "docs" / "guides" / "cheatsheet.md").write_text(head + main_rows + "\n## A to Z\n\n<!-- index:start -->\n<!-- index:end -->\n")
    (tmp_path / "docs" / "guides" / "cheatsheet-advanced.md").write_text("# Advanced\n\n## Setup\n\n| Command | Does |\n|---|---|\n" + adv_rows)
    return str(tmp_path)


def test_the_real_cheat_sheet_follows_its_own_rules_and_the_index_is_current():
    assert G.errors() == []
    assert (Path(G.ROOT) / "docs" / "guides" / "cheatsheet.md").read_text() == G.build()
    assert "`g2mic`" in G.build_index() and "`g2power`" in G.build_index()


def test_a_row_must_be_an_example_not_the_grammar(tmp_path):
    root = _tree(tmp_path, "| `g2mic [status\\|on\\|off [MIN]]` | wake word |\n| `g2mic off 30` | wake word off for 30 minutes |\n")
    bad = G.errors(root)
    assert len(bad) == 1 and "grammar" in bad[0]


def test_long_descriptions_and_unknown_commands_are_refused(tmp_path):
    root = _tree(tmp_path, "| `g2rest` | " + "x" * 81 + " |\n| `g2nothing now` | does nothing |\n| `python -m pi_pipeline.power status` | any module path is fine |\n")
    bad = G.errors(root)
    assert any("81 characters" in b for b in bad) and any("g2nothing" in b for b in bad) and len(bad) == 2


def test_the_index_lists_each_command_once_with_every_section_it_is_in(tmp_path):
    root = _tree(tmp_path, "| `g2mic off 30` | off |\n| `g2mic on` | on |\n| `g2rest` | rest |\n", "| `g2rest` | rest again |\n| `g2back` | go back |\n")
    idx = G.build_index(root)
    assert idx.count("`g2mic`") == 1 and "[Voice and mic](#voice-and-mic)" in idx
    rest = [line for line in idx.splitlines() if line.startswith("| `g2rest`")][0]
    assert "(#voice-and-mic)" in rest and "cheatsheet-advanced.md#setup" in rest
    assert idx.index("`g2back`") < idx.index("`g2mic`") < idx.index("`g2rest`")                       # A to Z
    assert "<!-- index:start -->\n| Command" in G.build(root)
