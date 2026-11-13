"""The Goals tab's success since the start (tools/g2_goals_series.js): the arithmetic runs in node with no page; the page is checked for the file and the hooks."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
SPEC = importlib.util.spec_from_file_location("g2_review_series", TOOLS / "g2_review.py")
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)
NODE = shutil.which("node")


def test_the_page_has_the_series_code_and_the_goal_card_uses_it():
    page = G.PAGE
    assert "/*GOALS_SERIES*/" not in page and "function goalSeries" in page and page.index("function goalSeries") < page.index("function goalCard")      # defined before the Goals tab code
    for hook in ("goalSeries(g.attempts)", "goalChart(S)", "goalTrendText(S)"):
        assert hook in page, hook


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_whole_page_script_still_parses(tmp_path):
    js = G.PAGE.replace("__TOKEN__", "t").split("<script>", 1)[1].rsplit("</script>", 1)[0]
    f = tmp_path / "page.js"
    f.write_text(js)
    r = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _run(tmp_path, attempts):
    f = tmp_path / "t.js"
    f.write_text("const {goalSeries,trendText}=require(%r);const a=%s;const s=goalSeries(a);"
                 "console.log(JSON.stringify({s:{n:s.n,wins:s.wins,overall:s.overall,roll:s.roll,trend:s.trend,changes:s.changes,halves:[s.firstHalf,s.secondHalf],cum:s.points.map(p=>p.cum),rolls:s.points.map(p=>p.roll)},text:trendText(s)}))"
                 % (str(TOOLS / "g2_goals_series.js"), json.dumps(attempts)))
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def att(i, ok, counted=True, cond=None):
    return {"number": i, "raw_time": "2026-11-%02d 10:00:00" % (i % 28 + 1) if False else "2026-11-01 10:%02d:00" % i, "time": "t%d" % i, "success": ok, "counted": counted, "conditions": cond or {"attachment": "arm", "floor": "hardwood", "hw": "e1"}}


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_success_since_the_start_the_last_attempts_and_the_trend_are_counted_attempts_only(tmp_path):
    rows = [att(i, i >= 10) for i in range(20)]                                              # 10 bad, then 10 good: improving
    rows.append(att(30, True, counted=False))                                                # an attempt that is not counted does not move anything
    out = _run(tmp_path, list(reversed(rows)))                                               # in any order: the series sorts by time
    s = out["s"]
    assert s["n"] == 20 and s["wins"] == 10 and s["overall"] == 0.5 and s["roll"] == 1.0
    assert s["trend"]["w"] == 10 and s["trend"]["last"] == 1.0 and s["trend"]["prev"] == 0.0 and s["trend"]["delta"] == 1.0
    assert s["cum"][0] == 0.0 and s["cum"][-1] == 0.5 and s["rolls"][-1] == 1.0 and s["rolls"][9] == 0.0
    assert out["text"].startswith("▲") and "+100" in out["text"] and s["halves"] == [0.0, 1.0]


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_falling_rate_is_down_and_too_few_attempts_say_so_and_a_changed_setting_is_marked(tmp_path):
    down = _run(tmp_path, [att(i, i < 10) for i in range(20)])
    assert down["text"].startswith("▼") and down["s"]["trend"]["delta"] == -1.0
    few = _run(tmp_path, [att(i, True) for i in range(4)])
    assert few["s"]["trend"] is None and "at least 6" in few["text"]
    none = _run(tmp_path, [])
    assert none["s"]["n"] == 0 and none["s"]["overall"] is None and none["text"] == "no counted attempts yet"
    changed = _run(tmp_path, [att(i, True, cond={"attachment": "arm", "floor": "hardwood", "hw": "e1" if i < 5 else "e2"}) for i in range(10)])
    assert changed["s"]["changes"] == [{"at": 5, "from": "arm | hardwood | e1", "to": "arm | hardwood | e2"}]


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_chart_draws_a_dot_and_a_strip_entry_per_attempt_with_a_minimal_page_stub(tmp_path):
    f = tmp_path / "chart.js"
    f.write_text(
        "class N{constructor(t){this.tag=t;this.kids=[];this.at={};this.style={};this.textContent=''}setAttribute(k,v){this.at[k]=v}append(...k){this.kids.push(...k)}}\n"
        "global.window={};global.document={createElementNS:(ns,t)=>new N(t),createElement:t=>new N(t),createTextNode:x=>({text:x})};\n"
        "require(%r);const rows=[];for(let i=0;i<30;i++)rows.push({number:i,raw_time:'2026-11-01 10:'+String(i).padStart(2,'0'),time:'t'+i,success:i%%3!==0,counted:true,conditions:{hw:i<15?'a':'b'}});\n"
        "const s=window.goalSeries(rows);const [svg,cap]=window.goalChart(s);const count=t=>svg.kids.filter(k=>k.tag===t).length;\n"
        "console.log(JSON.stringify({circles:count('circle'),rects:count('rect'),paths:count('path'),dashed:svg.kids.filter(k=>k.tag==='line'&&k.at['stroke-dasharray']).length,cap:cap.kids.length>0}))\n" % str(TOOLS / "g2_goals_series.js"))
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out == {"circles": 30, "rects": 30, "paths": 2, "dashed": 1, "cap": True}          # a dot and a strip entry per attempt, the two lines, one dotted change line


def test_every_goals_tab_section_starts_collapsed_and_every_goal_card_starts_open():
    """Owner, 2026-11-12: the sections start collapsed; each goal's summary (its card: numbers and charts) is the one thing open."""
    import re
    js = (TOOLS / "g2_goals_ui.js").read_text()
    assert len(re.findall(r"(?<![A-Za-z_])fold\(", js)) == 1                                  # only the helper itself calls the page's fold(); every section goes through it
    assert "const gfold=(title)=>fold(title,false)" in js
    assert re.search(r"function goalOpen\(id,i\)\{.*return true\}", js, re.S)                  # no saved choice: open
    assert 'g2GoalOpenV' in js                                                                  # the choices saved under the old rule are dropped once
