"""The Pictures tab of the review page (tools/g2_review.py): pick several pictures and give them one room (tools/g2_pics_select_ui.js). The page code is checked for its hooks and its syntax, and the
choosing logic is run in node with no page."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
SPEC = importlib.util.spec_from_file_location("g2_review_sel", TOOLS / "g2_review.py")
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)
NODE = shutil.which("node")


def test_the_page_has_the_selection_boxes_the_group_buttons_and_the_room_bar():
    page = G.PAGE
    assert "/*SELECT_UI*/" not in page and "window.picSelect=" in page and "selbar" in page          # the file is inserted
    for hook in ('picSelect.begin(tab==="pictures")', "picSelect.groupButtons(groups[g])", "picSelect.attach(c,p,groups[g])", "picSelect.end()", "picSelect.leave()"):
        assert hook in page, hook
    assert 'p.group!=="looks"' in page.split("picSelect.attach")[0][-200:]                          # look pictures get no box: they are throwaways with no room


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_whole_page_script_parses(tmp_path):
    page = G.PAGE.replace("__TOKEN__", "t")
    js = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    f = tmp_path / "page.js"
    f.write_text(js)
    r = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_picking_one_by_one_a_range_with_shift_and_a_whole_group(tmp_path):
    script = tmp_path / "t.js"
    script.write_text(
        "global.window={};global.document=undefined;\n"
        "eval(require('fs').readFileSync(%r,'utf8'));\n"
        "const L=window.picSelect._logic;const g=['a','b','c','d','e'].map(n=>({path:'x/'+n+'.jpg'}));const other=[{path:'y/z.jpg'}];const out={};\n"
        "L.click(g,'x/c.jpg',true,false);out.one=L.selection();\n"
        "L.click(g,'x/a.jpg',true,true);out.shift_up=L.selection().sort();\n"                          # Shift from c back to a: a, b, c
        "L.click(g,'x/e.jpg',true,true);out.shift_down=L.selection().sort();\n"                         # Shift from a to e: all five
        "L.click(g,'x/b.jpg',false,false);out.off=L.selection().sort();out.all_in=L.allIn(g);\n"
        "L.reset();L.click(g,'x/b.jpg',true,false);L.click(other,'y/z.jpg',true,true);out.other_group=L.selection().sort();\n"       # Shift across groups is one box, not a range
        "L.choose(g.map(q=>q.path),true);out.group=L.allIn(g);L.choose(g.map(q=>q.path),false);out.none=L.selection();\n"
        "out.range_missing=L.rangePaths(g,'x/zz.jpg','x/a.jpg');console.log(JSON.stringify(out));\n" % str(TOOLS / "g2_pics_select_ui.js"))
    r = subprocess.run([NODE, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["one"] == ["x/c.jpg"]
    assert out["shift_up"] == ["x/a.jpg", "x/b.jpg", "x/c.jpg"]
    assert out["shift_down"] == ["x/a.jpg", "x/b.jpg", "x/c.jpg", "x/d.jpg", "x/e.jpg"]
    assert out["off"] == ["x/a.jpg", "x/c.jpg", "x/d.jpg", "x/e.jpg"] and out["all_in"] is False
    assert out["other_group"] == ["x/b.jpg", "y/z.jpg"]
    assert out["group"] is True and out["none"] == ["y/z.jpg"]                  # dropping the group leaves the picture from the other group picked
    assert out["range_missing"] == ["x/a.jpg"]


def test_the_bar_can_name_the_selection_and_accept_g2s_guesses_and_a_group_can_select_by_guess():
    page = G.PAGE
    for hook in ("async function applyName", "async function acceptGuesses", "Name them", "Select by G2's guess", 'api("/api/pictures/name"'):
        assert hook in page, hook


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_select_by_guess_picks_every_picture_with_that_guess(tmp_path):
    script = tmp_path / "g.js"
    script.write_text(
        "class N{constructor(t,c,x){this.tag=t;this.className=c||'';this.kids=[];this.style={};this.value='';this.textContent=x||''}append(...k){this.kids.push(...k)}}\n"
        "global.window={};global.el=(t,c,x)=>new N(t,c,x);global.document={createElement:t=>new N(t)};\n"
        "eval(require('fs').readFileSync(%r,'utf8'));const S=window.picSelect;S.begin(false);\n"
        "const g=[{path:'a',guess:{label:'mug'}},{path:'b',guess:{label:'mug'}},{path:'c',guess:{label:'door'}},{path:'d'},{path:'e',guess:{label:'mug'},name:'mug'}];\n"
        "const w=S.groupButtons(g);const sel=w.kids[1];const opts=sel.kids.map(o=>o.textContent);\n"
        "sel.onclick={stopPropagation(){}};sel.value='mug';sel.onchange({stopPropagation(){}});\n"
        "console.log(JSON.stringify({opts,picked:S._logic.selection().sort(),menu:w.kids.length}));\n" % str(TOOLS / "g2_pics_select_ui.js"))
    r = subprocess.run([NODE, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["opts"] == ["Select by G2's guess...", "mug (2)", "door (1)"]              # an already named picture is not counted
    assert out["picked"] == ["a", "b"] and out["menu"] == 2
