"""HTML report for the V3 pre-20M benchmark (docs/rl/v3-retrain-plan.md Phase 5-6; phase_v3.py's "report" job runs it).

    python v3_report.py --v21 A.json --control B.json --k3 C.json --final D.json --results trained/v3_results.json --out report.html
    python v3_report.py --demo --out /tmp/demo.html          # builds a page from whatever is in trained/ (for checking the layout)

Inputs are benchmark_v4.run() result files (bench version 5: cells + the difficulty ladder). Output is ONE self-contained HTML page (inline CSS and SVG, Google Fonts
only, light and dark themes) written as page content, with no doctype or head, so it can be published as an Artifact as it is.

Sections: the promotion check against the V2.1 reference, the difficulty-level ladder (training's levels, scored on the finished policy), every benchmark cell,
straightness (heading drift, left/right asymmetry), the seed replicates, the training history, and what the sim cannot tell us.
"""
import argparse
import glob
import html
import json
import os
import time

import numpy as np

SERIES = [("v21", "V2.1 (deployed)", "var(--s1)"), ("control", "V3 control (no levers)", "var(--s3)"), ("k3", "V3 base (K3)", "var(--s4)"),
          ("final", "V3 final stage", "var(--s2)")]
DECISION_CELLS = ["T1.1", "N1", "N3", "N5", "T2.2", "T3.2", "T5.2", "T7.2", "T8.1", "T9.1", "T10.2", "T11.1"]
CATS = ("terrain", "ledge", "slope", "fault")
LEVELS = (0.25, 0.5, 0.75, 1.0)
# the promotion rule, docs/rl/v3-retrain-plan.md Phase 7
CALM_FALLS_MAX, HEADING_MAX_DEG, FALLS_WORSE_MAX, SPEED_MIN_RATIO = 0.15, 30.0, 0.10, 0.95

CSS = """
:root{--bg:#f5f7f6;--surface:#ffffff;--ink:#13201f;--ink2:#46564f;--muted:#76857f;--line:#dde4e1;--line2:#eef2f0;--accent:#0b6b62;--accent-bg:#e2f1ee;
--good:#18794a;--good-bg:#e2f3ea;--warn:#a85f00;--warn-bg:#fbefd9;--bad:#b83227;--bad-bg:#fbe5e2;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--grid:#e3e9e6;
--font:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1514;--surface:#172120;--ink:#e9f0ee;--ink2:#b3c1bc;--muted:#869590;--line:#2a3836;--line2:#202c2a;--accent:#4fc4b6;--accent-bg:#14312e;
--good:#4fc58a;--good-bg:#12301f;--warn:#e0a24a;--warn-bg:#352711;--bad:#f0746a;--bad-bg:#3b1a17;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--grid:#26332f;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f1514;--surface:#172120;--ink:#e9f0ee;--ink2:#b3c1bc;--muted:#869590;--line:#2a3836;--line2:#202c2a;--accent:#4fc4b6;--accent-bg:#14312e;
--good:#4fc58a;--good-bg:#12301f;--warn:#e0a24a;--warn-bg:#352711;--bad:#f0746a;--bad-bg:#3b1a17;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--grid:#26332f;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font-family:var(--font);font-size:15px;line-height:1.55}
.page{max-width:1080px;margin:0 auto;padding-block:28px 56px;padding-inline:16px;display:flex;flex-direction:column;gap:28px}
h1{font-size:1.9rem;line-height:1.15;margin:0;font-weight:600;letter-spacing:-.01em;text-wrap:balance}
h2{font-size:1.2rem;margin:0 0 4px;font-weight:600;text-wrap:balance}
h3{font-size:.95rem;margin:0 0 6px;font-weight:600}
p{margin:0}.lede{color:var(--ink2);max-width:68ch}.sub{color:var(--muted);font-size:.85rem}
.eyebrow{font-family:var(--mono);font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
section{display:flex;flex-direction:column;gap:12px;min-width:0}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:16px;min-width:0}
.verdict{border-radius:8px;padding:16px 18px;border:1px solid var(--line);display:flex;flex-direction:column;gap:10px}
.verdict.pass{background:var(--good-bg);border-color:var(--good)}.verdict.fail{background:var(--bad-bg);border-color:var(--bad)}.verdict.mixed{background:var(--warn-bg);border-color:var(--warn)}
.verdict .big{font-size:1.25rem;font-weight:600}
.crit{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
.crit div{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:10px 12px;min-width:0}
.crit .t{font-size:.8rem;color:var(--ink2)}.crit .v{font-family:var(--mono);font-size:.9rem;margin-top:2px}
.tag{display:inline-block;font-family:var(--mono);font-size:.72rem;padding:1px 7px;border-radius:4px;border:1px solid currentColor;white-space:nowrap}
.ok{color:var(--good)}.no{color:var(--bad)}.mid{color:var(--warn)}.mut{color:var(--muted)}
.scroll{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:.85rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;text-align:right;border-bottom:1px solid var(--line2);white-space:nowrap}
th:first-child,td:first-child{text-align:left}td.l,th.l{text-align:left;white-space:normal;min-width:220px}
thead th{font-weight:600;color:var(--ink2);border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--surface)}
td.n{font-family:var(--mono)}tr.grp td{background:var(--line2);font-weight:600;text-align:left}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:.85rem}.legend span{display:inline-flex;align-items:center;gap:7px}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.chart{min-width:0}.chart svg{width:100%;height:auto;display:block}
svg text{font-family:var(--font);fill:var(--ink2);font-size:11px}svg .ax{stroke:var(--line);stroke-width:1}svg .gr{stroke:var(--grid);stroke-width:1}
svg .thr{stroke:var(--muted);stroke-width:1;stroke-dasharray:4 3}
ul.plain{margin:0;padding-left:1.1rem;display:flex;flex-direction:column;gap:6px;max-width:80ch}
details summary{cursor:pointer;color:var(--accent);font-size:.88rem}
.note{font-size:.85rem;color:var(--ink2);max-width:80ch}
footer{color:var(--muted);font-size:.8rem}
.tag.good{color:var(--good);background:var(--good-bg)}.tag.bad{color:var(--bad);background:var(--bad-bg)}
.gifs{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.gif{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px;min-width:0}
.gif img{width:100%;height:auto;display:block;border-radius:4px}.gif figcaption{font-size:.82rem;color:var(--ink2);margin-top:6px}
"""


def load(path):
    return json.load(open(path)) if path and os.path.exists(path) else None


def e(x):
    return html.escape(str(x))


def cells(res):
    return {c["id"]: c for c in res["cells"]} if res else {}


def pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def num(x, f="{:.3f}"):
    return "n/a" if x is None else f.format(x)


# ----------------------------------------------------------------------------------------------- verdict
def verdict(final, ref):
    """The promotion rule against the V2.1 reference. Returns (list of (name, ok, detail)), overall class."""
    if not final or not ref:
        return [], "mixed"
    f, r = cells(final), cells(ref)
    out = []
    t11, n1 = f.get("T1.1"), f.get("N1")
    ok = bool(t11 and n1 and t11["fell_fraction"] <= CALM_FALLS_MAX and n1["fell_fraction"] <= CALM_FALLS_MAX)
    out.append(("Calm walk falls at most 15%", ok, f"T1.1 {pct(t11 and t11['fell_fraction'])}, N1 {pct(n1 and n1['fell_fraction'])}"))
    hd = n1["heading_mean_deg"] if n1 else None
    out.append(("12.5 s heading change within 30 deg (sim)", hd is not None and abs(hd) <= HEADING_MAX_DEG, f"N1 {num(hd, '{:+.1f}')} deg (V2.1 {num(r.get('N1', {}).get('heading_mean_deg'), '{:+.1f}')})"))
    worse = [(c, f[c]["fell_fraction"], r[c]["fell_fraction"]) for c in DECISION_CELLS if c in f and c in r and f[c]["fell_fraction"] > r[c]["fell_fraction"] + FALLS_WORSE_MAX]
    out.append(("No category falls 10 points more than V2.1", not worse,
                "all decision cells within 10 points" if not worse else "; ".join(f"{c} {a:.0%} vs {b:.0%}" for c, a, b in worse)))
    sp = [(c, f[c]["speed_mps"], r[c]["speed_mps"]) for c in ("T1.1", "N1") if c in f and c in r]
    slow = [(c, a, b) for c, a, b in sp if a < SPEED_MIN_RATIO * b]
    out.append(("Speed at least 95% of V2.1", bool(sp) and not slow, ", ".join(f"{c} {a:.3f} vs {b:.3f} m/s" for c, a, b in sp)))
    n_ok = sum(1 for _, ok, _ in out if ok)
    return out, ("pass" if n_ok == len(out) else "fail" if n_ok <= 1 else "mixed")


# ----------------------------------------------------------------------------------------------- charts
def ladder_chart(cat, results):
    """One small multiple: relative score vs level for each policy that has a ladder; dashed line at the promotion threshold."""
    W, H, L, R, T, B = 340, 230, 38, 14, 14, 44
    xs = {0.25: 0, 0.5: 1, 0.75: 2, 1.0: 3, "hard": 4}
    px = lambda k: L + (W - L - R) * xs[k] / 4
    py = lambda v: T + (H - T - B) * (1 - v)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Relative score by level, {e(cat)}">']
    for v in (0, .25, .5, .75, 1.0):
        out.append(f'<line class="gr" x1="{L}" x2="{W - R}" y1="{py(v):.1f}" y2="{py(v):.1f}"/><text x="{L - 6}" y="{py(v) + 4:.1f}" text-anchor="end">{v:.2f}</text>')
    for k, lab in ((0.25, "0.25"), (0.5, "0.50"), (0.75, "0.75"), (1.0, "1.00"), ("hard", "1.00 +10%")):
        out.append(f'<text x="{px(k):.1f}" y="{H - 24}" text-anchor="middle">{lab}</text>')
    out.append(f'<text x="{(L + W - R) / 2:.1f}" y="{H - 6}" text-anchor="middle">difficulty level</text>')
    up = None
    for key, name, color in SERIES:
        res = results.get(key)
        sm = res and res.get("ladder", {}).get("summary")
        if not sm:
            continue
        c = sm["categories"][cat]
        up = sm["up"]
        pts = [(px(l), py(c["rel"][str(l)] if str(l) in c["rel"] else c["rel"].get(l, 0.0)), c["rel"].get(str(l), c["rel"].get(l)), l) for l in LEVELS]
        if c["hard_rel"] is not None:
            pts.append((px("hard"), py(c["hard_rel"]), c["hard_rel"], "hard"))
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in pts)
        out.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for x, y, v, l in pts:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{color}" stroke="var(--surface)" stroke-width="2"><title>{e(name)}, level {e(l)}: {v:.2f}</title></circle>')
    if up is not None:
        out.append(f'<line class="thr" x1="{L}" x2="{W - R}" y1="{py(up):.1f}" y2="{py(up):.1f}"/><text x="{W - R}" y="{py(up) - 4:.1f}" text-anchor="end">ready at {up:.2f}</text>')
    out.append("</svg>")
    return "".join(out)


def legend(results):
    return '<div class="legend">' + "".join(f'<span><i class="sw" style="background:{c}"></i>{e(n)}</span>' for k, n, c in SERIES if results.get(k)) + "</div>"


# ----------------------------------------------------------------------------------------------- sections
def sec_verdict(results):
    crit, cls = verdict(results.get("final"), results.get("v21"))
    if not crit:
        return '<section><h2>Promotion check</h2><p class="note">The final stage or the V2.1 reference has not been scored yet.</p></section>'
    n_ok = sum(1 for _, ok, _ in crit if ok)
    head = {"pass": "Meets every promotion criterion", "mixed": f"Meets {n_ok} of {len(crit)} promotion criteria", "fail": f"Meets {n_ok} of {len(crit)} promotion criteria"}[cls]
    cards = "".join(f'<div><div class="t"><span class="tag {"ok" if ok else "no"}">{"MET" if ok else "MISSED"}</span> {e(n)}</div><div class="v">{e(d)}</div></div>' for n, ok, d in crit)
    return (f'<section><h2>Promotion check</h2><div class="verdict {cls}"><div class="big">{e(head)}</div>'
            f'<p class="note">The V3 final stage scored against the frozen V2.1 on the same cells and seeds, using the promotion rule in the retrain plan. The sim cannot show G2\'s real drift, so the '
            f'heading criterion is the weakest of the four; the real-floor walks decide that one.</p><div class="crit">{cards}</div></div></section>')


def sec_ladder(results):
    have = [r for r in results.values() if r and r.get("ladder")]
    if not have:
        return '<section><h2>Difficulty-level ladder</h2><p class="note">No ladder scores in these results (benchmark version 5 and the ladder flag are needed).</p></section>'
    charts = "".join(f'<div class="chart"><h3>{c.title()}</h3>{ladder_chart(c, results)}</div>' for c in CATS)
    rows = []
    for key, name, color in SERIES:
        sm = (results.get(key) or {}).get("ladder", {}).get("summary")
        if not sm:
            continue
        cs = sm["categories"]
        rows.append(f'<tr><td><i class="sw" style="background:{color}"></i> {e(name)}</td><td class="n">{sm["clean_score"]:.2f}</td>'
                    + "".join(f'<td class="n">{cs[c]["competence"]:.2f}</td>' for c in CATS) + f'<td class="n">{sm["mean_competence"]:.2f}</td></tr>')
    return (f'<section><h2>Difficulty-level ladder</h2><p class="lede">Training raises four hazard categories from 0 to 1 as the policy earns it. This runs the finished policies at fixed levels, in the same world the final '
            f'stage trains in, with the same score and the same 0.80 "ready" threshold the curriculum uses. A category counts as reached up to the last level where the score, relative to '
            f'the policy\'s own clean-floor score, stays at or above 0.80. The last point is level 1.0 with the hardest levels raised 10%, the world the 20M run trains in.</p>'
            f'{legend(results)}<div class="panel"><div class="charts">{charts}</div></div>'
            f'<div class="panel scroll"><h3>Level reached</h3><table><thead><tr><th>Policy</th><th>Clean floor</th>' + "".join(f"<th>{c}</th>" for c in CATS)
            + f'<th>Mean</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')


def delta_tag(v, ref, lower_better=True, tol=0.05):
    if ref is None or v is None:
        return ""
    d = v - ref
    if abs(d) <= tol:
        return ""
    better = (d < 0) == lower_better
    return f' <span class="{"ok" if better else "no"}">{"▼" if d < 0 else "▲"}</span>'


def sec_cells(results):
    base = results.get("v21")
    ref = cells(base)
    keys = [(k, n) for k, n, _ in SERIES if results.get(k)]
    allc = {}
    for k, _ in keys:
        for cid, c in cells(results[k]).items():
            allc.setdefault(cid, c)
    head = "".join(f'<th colspan="3">{e(n)}</th>' for k, n in keys)
    sub = "".join("<th>falls</th><th>m/s</th><th>head°</th>" for _ in keys)
    body = []
    for cid, c in allc.items():
        tds = []
        for k, _ in keys:
            x = cells(results[k]).get(cid)
            if not x:
                tds.append('<td class="mut">-</td>' * 3)
                continue
            r = ref.get(cid) if k != "v21" else None
            tds.append(f'<td class="n">{pct(x["fell_fraction"])}{delta_tag(x["fell_fraction"], r and r["fell_fraction"], True, 0.10) if r else ""}</td>'
                       f'<td class="n">{x["speed_mps"]:.3f}</td><td class="n">{x["heading_mean_deg"]:+.0f}</td>')
        body.append(f'<tr><td class="l"><b>{e(cid)}</b> <span class="sub">{e(c["label"])}{" (info only)" if c.get("tag") == "info" else ""}</span></td>{"".join(tds)}</tr>')
    return (f'<section><h2>Every benchmark cell</h2><p class="lede">Fall fraction, forward speed and heading change per cell, {e(next(iter(results.values()))["episodes"])} episodes '
            f'per cell by default and the same seeds for every policy. A green or red triangle marks a fall rate more than 10 points better or worse than V2.1. Fall rates from 20-40 episodes carry about '
            f'15 points of noise, so read single cells loosely.</p><div class="panel scroll"><table><thead><tr><th class="l">Cell</th>{head}</tr><tr><th class="l"></th>{sub}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></section>')


def sec_straight(results):
    rows = []
    for k, n, c in SERIES:
        r = results.get(k)
        if not r:
            continue
        cm = cells(r)
        g = lambda cid, key, f="{:+.1f}": f.format(cm[cid][key]) if cid in cm else "n/a"
        mg = r.get("mirror_gap")
        rows.append(f'<tr><td><i class="sw" style="background:{c}"></i> {e(n)}</td><td class="n">{g("N1", "heading_mean_deg")}</td><td class="n">{g("N1", "heading_std_deg", "{:.1f}")}</td>'
                    f'<td class="n">{g("N3", "heading_mean_deg")}</td><td class="n">{g("N5", "heading_abs_mean_deg", "{:.1f}")}</td><td class="n">{g("N1", "lr_asym_max_deg", "{:.1f}")}</td>'
                    f'<td class="n">{g("N1", "roll_std_deg", "{:.1f}")}</td><td class="n">{"n/a" if mg is None else f"{mg:.3f}"}</td></tr>')
    return ('<section><h2>Straightness</h2><p class="lede">The drift question. N1 is the calm 12.5 s walk; N3 has the front-left shoulder stuck at 42 degrees; N5 adds a constant yaw push. '
            'Left/right asymmetry is the largest difference between mirrored joints\' mean commands, which is what a learned one-sided bias looks like. The mirror gap is how far the policy is from '
            'treating left and right the same (0 is symmetric).</p><div class="panel scroll"><table><thead><tr><th>Policy</th><th>N1 heading°</th><th>N1 spread°</th><th>N3 heading°</th>'
            f'<th>N5 |heading|°</th><th>L/R asym°</th><th>Roll std°</th><th>Mirror gap</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            '<p class="sub">In the sim, V2.1 drifts about -4 degrees over 12.5 s; on G2 it drifted +36 +/- 25 right after the servo swap. The sim has not reproduced the real drift.</p></section>')


def sec_replicates(training):
    """Seed replicates: control, S1 (mirror), S2 (heading input) and the combination, one row per run, with the group means."""
    groups = [("Control (same recipe, no lever)", lambda t: t in ("v3_c0", "v3_c0b") or t.startswith("v3_r_c0_")),
              ("S1 mirror-symmetry loss", lambda t: t == "v3_s1_mirror" or t.startswith("v3_r_s1_")),
              ("S2 heading-error input", lambda t: t == "v3_s2_heading_obs" or t.startswith("v3_r_s2_")),
              ("S1 + S2 combined", lambda t: t.startswith("v3_r_s12_"))]
    rows, any_row = [], False
    for gname, pred in groups:
        runs = []
        for tag, rec in training.items():
            if pred(tag) and rec.get("result_file") and os.path.exists(rec["result_file"]):
                cm = cells(json.load(open(rec["result_file"])))
                if "N1" in cm and "N5" in cm and "T1.1" in cm:
                    runs.append((tag, cm))
        if not runs:
            continue
        any_row = True
        rows.append(f'<tr class="grp"><td colspan="7">{e(gname)}</td></tr>')
        for tag, cm in runs:
            seed = tag.rsplit("_s", 1)[-1] if "_r_" in tag else "42"
            probe = "6" if tag in ("v3_c0", "v3_s1_mirror") else "12"
            rows.append(f'<tr><td class="l">{e(tag)} <span class="sub">seed {seed}, {probe}-episode probe</span></td><td class="n">{cm["N1"]["heading_mean_deg"]:+.1f}</td><td class="n">{cm["N5"]["heading_abs_mean_deg"]:.1f}</td>'
                        f'<td class="n">{cm["N1"]["lr_asym_max_deg"]:.1f}</td><td class="n">{cm["N1"]["speed_mps"]:.3f}</td><td class="n">{pct(cm["T1.1"]["fell_fraction"])}</td><td class="n">{pct(cm["N2"]["fell_fraction"]) if "N2" in cm else "n/a"}</td></tr>')
        n = len(runs)
        mean = lambda f: sum(f(cm) for _, cm in runs) / n
        rows.append(f'<tr><td class="l"><i>mean of {n}</i></td><td class="n"><i>{mean(lambda c: abs(c["N1"]["heading_mean_deg"])):.1f} abs</i></td><td class="n"><i>{mean(lambda c: c["N5"]["heading_abs_mean_deg"]):.1f}</i></td>'
                    f'<td class="n"><i>{mean(lambda c: c["N1"]["lr_asym_max_deg"]):.1f}</i></td><td class="n"><i>{mean(lambda c: c["N1"]["speed_mps"]):.3f}</i></td><td class="n"><i>{mean(lambda c: c["T1.1"]["fell_fraction"]):.0%}</i></td><td class="n"></td></tr>')
    if not any_row:
        return ""
    return ('<section><h2>Seed replicates</h2><p class="lede">Each lever was screened first at one seed. These are the extra seeds, with the control repeated at each, so a result can be read against how much '
            'the same recipe varies run to run. Every run is 3M steps, scored on the same cells and seeds.</p><div class="panel scroll"><table><thead><tr><th class="l">Run</th><th>N1 heading°</th>'
            f'<th>N5 |heading|°</th><th>L/R asym°</th><th>N1 m/s</th><th>T1.1 falls</th><th>60 s falls</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')


def sec_history(training):
    rows = []
    for tag, rec in training.items():
        if rec.get("kind") not in ("screen", "combo", "stage", "final", "replicate"):
            continue
        st = {True: '<span class="tag ok">PASS</span>', False: '<span class="tag no">FAIL</span>', None: '<span class="tag mut">scored</span>'}[rec.get("passed")]
        why = "; ".join(rec.get("why") or [])
        rows.append(f'<tr><td class="l"><b>{e(tag)}</b> <span class="sub">{e(", ".join(rec.get("levers") or []) or "no levers")}</span></td><td>{st}</td><td class="l sub">{e(why or rec.get("summary", ""))[:260]}</td></tr>')
    if not rows:
        return ""
    return (f'<section><h2>Training history</h2><p class="lede">Every run the V3 pipeline has scored, in order. A screen passes when the calm walk does not regress against the control and its own target improves.</p>'
            f'<div class="panel scroll"><table><thead><tr><th class="l">Run</th><th>Verdict</th><th class="l">Detail</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')


def sec_reached(reached):
    """Difficulty reached IN TRAINING per challenge type (user, 2026-10-08): reached = {series key: {"note": str, "rows": {challenge: text}}} (phase_v4.difficulty_reached)."""
    if not reached:
        return ""
    keys = [(k, n, c) for k, n, c in SERIES if k in reached]
    challenges = []
    for k, _, _ in keys:
        for ch in reached[k]["rows"]:
            if ch not in challenges:
                challenges.append(ch)
    head = "".join(f'<th><i class="sw" style="background:{c}"></i> {e(n)}</th>' for k, n, c in keys)
    body = "".join(f'<tr><td class="l">{e(ch)}</td>' + "".join(f'<td class="l">{e(reached[k]["rows"].get(ch, "not in its course"))}</td>' for k, _, _ in keys) + "</tr>" for ch in challenges)
    notes = "".join(f'<li><b>{e(n)}</b>: {e(reached[k]["note"])}</li>' for k, n, _ in keys)
    return (f'<section><h2>Difficulty reached in training</h2><p class="lede">The hardest size of each challenge each policy was training at when its run ended. '
            f'This is what the training curriculum had earned, not a benchmark score; the ladder above measures the finished policies on fixed levels.</p>'
            f'<ul class="plain">{notes}</ul><div class="panel scroll"><table><thead><tr><th class="l">Challenge</th>{head}</tr></thead><tbody>{body}</tbody></table></div></section>')


def _binom_two_sided(k, n):
    """Exact two-sided sign-test p-value for k of n discordant pairs going one way (McNemar)."""
    from math import comb
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def sec_paired(results):
    """Per cell, the reference (V3) and the candidate (V4) met the SAME courses (seeded episodes), so falls are compared pair by pair (McNemar's exact test) and
    speed by the paired difference; a verdict only when it is unlikely to be noise (p < 0.05; speed: the 95% interval excludes 0 and the change is >= 3 mm/s)."""
    a, b = results.get("v21"), results.get("final")
    if not (a and b):
        return ""
    ca, cb = {c["id"]: c for c in a["cells"]}, {c["id"]: c for c in b["cells"]}
    rows, better, worse = [], 0, 0
    for cid, x in ca.items():
        y = cb.get(cid)
        if not y or "ep_fell" not in x or "ep_fell" not in y or len(x["ep_fell"]) != len(y["ep_fell"]):
            continue
        fa, fb = x["ep_fell"], y["ep_fell"]
        only_a = sum(1 for u, v in zip(fa, fb) if u and not v)
        only_b = sum(1 for u, v in zip(fa, fb) if v and not u)
        pf = _binom_two_sided(min(only_a, only_b), only_a + only_b)
        d = np.array(y["ep_speed"]) - np.array(x["ep_speed"])
        md, half = float(d.mean()), float(1.96 * d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0
        verdicts = []
        if pf < 0.05:
            verdicts.append(("fewer falls" if only_a > only_b else "more falls", only_a > only_b))
        if abs(md) >= 0.003 and abs(md) > half:
            verdicts.append(("faster" if md > 0 else "slower", md > 0))
        good = [v for v, ok in verdicts if ok]
        bad = [v for v, ok in verdicts if not ok]
        if bad and not good:
            worse += 1
            tag = '<span class="tag bad">V4 worse: ' + e(", ".join(bad)) + "</span>"
        elif good and not bad:
            better += 1
            tag = '<span class="tag good">V4 better: ' + e(", ".join(good)) + "</span>"
        elif good and bad:
            tag = '<span class="tag">mixed: ' + e(", ".join(good + bad)) + "</span>"
        else:
            tag = '<span class="tag">no clear difference</span>'
        rows.append(f'<tr><td class="l">{e(cid)} {e(x.get("label", ""))}</td><td class="n">{x["fell_fraction"]:.2f} &rarr; {y["fell_fraction"]:.2f}</td>'
                    f'<td class="n">{only_a} / {only_b}</td><td class="n">{pf:.3f}</td><td class="n">{md * 1000:+.1f} &plusmn; {half * 1000:.1f}</td><td class="l">{tag}</td></tr>')
    if not rows:
        return ""
    return (f'<section><h2>Cell by cell: real differences or noise?</h2><p class="lede">Both policies met the same courses (seeded episodes), so each cell is compared pair by pair. '
            f'Falls: the episodes only V3 fell vs only V4 fell, with an exact test; a verdict only below p = 0.05. Speed: the paired difference with its 95% interval. '
            f'<b>{better}</b> cells clearly better for V4, <b>{worse}</b> clearly worse, the rest within noise.</p><div class="panel scroll"><table><thead><tr><th class="l">Cell</th>'
            f'<th>Falls V3 &rarr; V4</th><th>Only V3 fell / only V4 fell</th><th>p (falls)</th><th>Speed change, mm/s</th><th class="l">Verdict</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></section>')


def sec_g2(results):
    """What to expect on G2: the calm 12.5 s walk (N1, as G2 is tested) side by side, with the known sim-to-real gaps."""
    keys = [(k, n) for k, n, _ in SERIES if results.get(k)]
    m = {k: next((c for c in results[k]["cells"] if c["id"] == "N1"), None) for k, _ in keys}
    if not any(m.values()):
        return ""
    def val(k, f, fmt):
        c = m.get(k)
        return fmt.format(c[f]) if c and f in c else "-"
    rows = [("Falls (calm 12.5 s walk)", "fell_fraction", "{:.2f}", "G2 falls more than the sim on tile: count them on the floor you test on"),
            ("Speed, m/s", "speed_mps", "{:.3f}", "the sim walks slower than G2 (about 0.09 vs 0.12 m/s at the same command): compare the two policies, not the sim value with G2"),
            ("Heading change over 12.5 s, deg (mean)", "heading_mean_deg", "{:+.1f}", "G2 turns right ~36 deg per 12.5 s without the front-foot hold; the sim drifts in a random direction"),
            ("Heading change, deg (mean of |value|)", "heading_abs_mean_deg", "{:.1f}", "with the hold on, G2's heading is set by the hold, not the policy"),
            ("Roll wobble, deg (std)", "roll_std_deg", "{:.1f}", "G2's measured roll std on tile: 5.4 deg"),
            ("Pitch wobble, deg (std)", "pitch_std_deg", "{:.1f}", "G2's measured pitch std on tile: 2.6 deg"),
            ("Joint speed over the servo limit (share of joints)", "servo_over_frac", "{:.2f}", "commands the servos cannot follow: lower is gentler on G2"),
            ("Swing clearance, mm (90th percentile)", "foot_clear_p90_mm", "{:.1f}", "how high the paws lift: higher clears carpet edges and cords"),
            ("Left-right joint asymmetry, deg (max)", "lr_asym_max_deg", "{:.1f}", "a one-sided stance turns G2 on the floor")]
    head = "".join(f"<th>{e(n)}</th>" for _, n in keys)
    body = "".join(f'<tr><td class="l">{e(lbl)}</td>' + "".join(f'<td class="n">{val(k, f, fmt)}</td>' for k, _ in keys) + f'<td class="l note">{e(note)}</td></tr>'
                   for lbl, f, fmt, note in rows)
    return (f'<section><h2>What to expect on G2</h2><p class="lede">The calm 12.5 s walk (N1), the cell closest to how G2 is tested, with what is known about the sim-to-real gap '
            f'for each number. Use it to plan the hardware runs and to read them against the sim.</p><div class="panel scroll"><table><thead><tr><th class="l">Measure</th>{head}'
            f'<th class="l">On the real G2</th></tr></thead><tbody>{body}</tbody></table></div></section>')


def sec_falls(results):
    """How each policy falls: which way, how long into the episode, and in which cells."""
    keys = [(k, n) for k, n, _ in SERIES if results.get(k)]
    blocks = []
    for k, n in keys:
        falls = [(c["id"], f) for c in results[k]["cells"] for f in c.get("ep_falls", [])]
        if not falls:
            blocks.append(f"<h3>{e(n)}</h3><p>No falls recorded (or the result predates per-episode records).</p>")
            continue
        ways = {}
        for _, f in falls:
            ways[f["way"]] = ways.get(f["way"], 0) + 1
        cells = {}
        for cid, _ in falls:
            cells[cid] = cells.get(cid, 0) + 1
        ts = sorted(f["t_s"] for _, f in falls)
        early = sum(1 for t in ts if t < 1.0)
        blocks.append(f"<h3>{e(n)}: {len(falls)} falls</h3><ul class='plain'>"
                      + f"<li>Which way: " + ", ".join(f"{e(w)} {v}" for w, v in sorted(ways.items(), key=lambda kv: -kv[1])) + "</li>"
                      + f"<li>When: median {ts[len(ts) // 2]:.1f} s into the episode; {early} within the first second</li>"
                      + f"<li>Where most: " + ", ".join(f"{e(c)} ({v})" for c, v in sorted(cells.items(), key=lambda kv: -kv[1])[:5]) + "</li></ul>")
    return (f'<section><h2>How they fall</h2><p class="lede">Every fall in every cell, by the direction the body tipped, how long into the episode, and where. '
            f'Sideways falls point at balance across the body; forward or backward falls at stepping and pitch; very early falls at the start pose or a hazard right at the start.</p>'
            f'<div class="panel">{"".join(blocks)}</div></section>')


def _svg_lines(series, xlabel, ylabel, w=640, h=220):
    """series: [(name, color, [(x, y), ...])] -> a small SVG line chart drawn to one scale."""
    pts = [p for _, _, s in series for p in s]
    if not pts:
        return ""
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    if x1 == x0:
        x1 = x0 + 1
    if y1 == y0:
        y1 = y0 + 1
    L, R, T, B = 52, 12, 10, 34
    sx = lambda x: L + (x - x0) / (x1 - x0) * (w - L - R)
    sy = lambda y: T + (1 - (y - y0) / (y1 - y0)) * (h - T - B)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart-svg" role="img" aria-label="{e(ylabel)} vs {e(xlabel)}">']
    for i in range(5):
        yv = y0 + (y1 - y0) * i / 4
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{sy(yv):.1f}" y2="{sy(yv):.1f}" stroke="var(--line)" stroke-width="1"/>'
                   f'<text x="{L - 6}" y="{sy(yv) + 4:.1f}" text-anchor="end" font-size="10" fill="var(--muted)">{yv:.3g}</text>')
    for i in range(5):
        xv = x0 + (x1 - x0) * i / 4
        out.append(f'<text x="{sx(xv):.1f}" y="{h - 14}" text-anchor="middle" font-size="10" fill="var(--muted)">{xv:.3g}</text>')
    out.append(f'<text x="{(L + w - R) / 2:.0f}" y="{h - 2}" text-anchor="middle" font-size="10" fill="var(--muted)">{e(xlabel)}</text>')
    for name, color, s in series:
        if s:
            out.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="' + " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in s) + '"/>')
    out.append("</svg>")
    return "".join(out)


def sec_training(train):
    """How each run trained (user, 2026-10-08): reward over the run, the fixed-difficulty eval and the curriculum's progress, why it stopped, and each hazard's success vs size."""
    if not train:
        return ""
    colors = {k: c for k, _, c in SERIES}
    names = {k: n for k, n, _ in SERIES}
    parts = []
    rew = [(names[k], colors[k], t.get("reward", [])) for k, t in train.items()]
    parts.append(f'<div class="chart"><h3>Mean episode reward over the run (millions of steps)</h3>{_svg_lines(rew, "steps (M)", "reward")}</div>')
    ev = [(names[k], colors[k], t.get("eval", [])) for k, t in train.items() if t.get("eval")]
    if ev:
        parts.append(f'<div class="chart"><h3>Fixed-difficulty eval every 1M steps (0-1)</h3>{_svg_lines(ev, "steps (M)", "eval")}</div>')
    notes = "".join(f"<li><b>{e(names[k])}</b>: {e(t.get('note', ''))}</li>" for k, t in train.items())
    curves = ""
    for k, t in train.items():
        fr = t.get("frontier_bins")
        if not fr:
            continue
        rows = []
        for h, (bins, bound, unit) in fr.items():
            cells = "".join((f'<td class="n">{v:.2f}<br><span class="note">n {nn}</span></td>' if nn else '<td class="n note">-</td>') for v, nn in bins)
            rows.append(f'<tr><td class="l">{e(h)}<br><span class="note">0-{bound:g} {e(unit)}</span></td>{cells}</tr>')
        nb = len(next(iter(fr.values()))[0])
        curves += (f'<div class="panel scroll"><h3>{e(names[k])}: success by size, each hazard (relative to a hazard-free walk; columns = size bins from small to the physical bound)</h3>'
                   f'<table><thead><tr><th class="l">Hazard</th>' + "".join(f"<th>{i + 1}</th>" for i in range(nb)) + f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return (f'<section><h2>How they trained</h2><ul class="plain">{notes}</ul>{legend({k: True for k in train})}<div class="panel"><div class="charts">{"".join(parts)}</div></div>'
            f'{curves}</section>')


def sec_gifs(gifs):
    """Side-by-side replays: the same course (same seed) for both policies, one GIF per cell (left V3, right V4)."""
    if not gifs:
        return ""
    items = "".join(f'<figure class="gif"><img src="{uri}" alt="{e(label)}: V3 left, V4 right" loading="lazy"><figcaption>{e(label)} &middot; '
                    f'{e(outcome)}</figcaption></figure>' for label, uri, outcome in gifs)
    return (f'<section><h2>Side by side</h2><p class="lede">The same course and the same random events for both policies (left V3, right V4), so differences are the policies'
            f' own. Deterministic actions, as on G2.</p><div class="gifs">{items}</div></section>')


def sec_delay(results, delay):
    """Reality-gap check: each policy's falls and speed with the 12.5 ms command delay G2's walks show, against the same cells as trained (4 ms)."""
    if not delay:
        return ""
    keys = [(k, n) for k, n, _ in SERIES if k in delay and results.get(k)]
    cells = [c["id"] for c in delay[keys[0][0]]["cells"]]
    rows = []
    for cid in cells:
        tds = []
        for k, _ in keys:
            base = next((c for c in results[k]["cells"] if c["id"] == cid), None)
            d = next((c for c in delay[k]["cells"] if c["id"] == cid), None)
            if base and d:
                tds.append(f'<td class="n">{base["fell_fraction"]:.2f} &rarr; {d["fell_fraction"]:.2f}</td><td class="n">{base["speed_mps"]:.3f} &rarr; {d["speed_mps"]:.3f}</td>')
            else:
                tds.append('<td class="n">-</td><td class="n">-</td>')
        label = next((c.get("label", "") for c in delay[keys[0][0]]["cells"] if c["id"] == cid), "")
        rows.append(f'<tr><td class="l">{e(cid)} {e(label)}</td>{"".join(tds)}</tr>')
    head = "".join(f'<th>{e(n)}: falls</th><th>{e(n)}: speed</th>' for _, n in keys)
    return (f'<section><h2>Reality-gap check: the measured command delay</h2><p class="lede">G2\'s walk logs show about 12.5 ms of command-path delay (the loop\'s 99th-percentile tick '
            f'minus its median); the sim trains with up to 4 ms. Each policy is scored again with 12.5 ms (evaluation only, nothing trains on it). Little change means the parameter does not '
            f'matter; a large drop means it is worth a training screen. Each cell: as scored above &rarr; with the delay.</p><div class="panel scroll"><table><thead><tr><th class="l">Cell</th>'
            f'{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')


def sec_caveats():
    items = [
        "The sim is calibrated to G2's roll and pitch while walking (servo speed 200 deg/s, motor force 0.15 N*m). It does not reproduce G2's real right drift, so a better heading number here is evidence, not proof.",
        "On G2, longer right strides turn G2 left, the opposite of the sim, so any steering behavior has to be confirmed on the floor.",
        "Fall rates from 20 to 40 episodes carry about 15 points of noise. Differences of a few points between runs mean little; the seed replicates show how much one recipe varies.",
        "The ladder's levels are training's own: level 1.0 is the hardest world the policy has trained in, not the hardest world that exists. The +10% rung is the extra margin the 20M run adds.",
        "Carpet is reported and never scored. G2 stalls on carpet with every gait, and the sim's carpet model is a guess.",
        "Speed in the sim is about 25% below G2's (0.09 vs 0.12 m/s); the Pi scales the commanded speed to compensate.",
    ]
    return '<section><h2>What these numbers cannot tell us</h2><ul class="plain">' + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul></section>"


def build(results, training, title="V3 Pre-20M Benchmark", labels=None, reached=None, train=None, gifs=None, delay=None):
    """labels: {"v21": "...", "final": "..."} renames the series (the V3 vs V4 report passes the deployed V3 as the reference "v21" slot and V4 as "final")."""
    global SERIES
    if labels:
        SERIES = [(k, labels.get(k, n), c) for k, n, c in SERIES]
    ref = results.get("v21") or next(iter(results.values()))
    fin = results.get("final")
    meta = (f'benchmark version {ref.get("bench_version", "?")}, {ref.get("episodes", "?")} episodes per cell, seed {ref.get("seed", "?")}'
            + (f', ladder {fin["ladder"]["episodes"]} episodes per rung' if fin and fin.get("ladder") else ""))
    parts = [f"<title>{e(title)}</title>", f"<style>{CSS}</style>",
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">',
             '<div class="page"><header><div class="eyebrow">G2 gait retrain / benchmark before the 20M decision</div>', f"<h1>{e(title)}</h1>",
             f'<p class="lede">Final-stage policy against the deployed V2.1, scored on the training-matched benchmark. {e(meta)}. Generated {time.strftime("%B %d, %Y, %I:%M %p")} Eastern.</p></header>',
             sec_verdict(results), sec_paired(results), sec_g2(results), sec_gifs(gifs), sec_ladder(results), sec_reached(reached), sec_training(train),
             sec_falls(results), sec_delay(results, delay), sec_straight(results), sec_cells(results), sec_replicates(training), sec_history(training), sec_caveats(),
             '<footer>Scores come from benchmark_v4.py (bench version 5) on the shared G2 profile in g2_profile.py. The 20M run starts only on your go.</footer></div>']
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v21")
    ap.add_argument("--control")
    ap.add_argument("--k3")
    ap.add_argument("--final")
    ap.add_argument("--results", default="trained/v3_results.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--demo", action="store_true", help="use whatever is in trained/: V2.1 reference, C0b, S1, S2 stand in for the four policies")
    a = ap.parse_args()
    if a.demo:
        a.v21, a.control, a.k3, a.final = "trained/v3_ref_v21.json", "trained/v3_score_v3_c0b.json", "trained/v3_score_v3_s1_mirror.json", "trained/v3_score_v3_s2_heading_obs.json"
    results = {k: load(p) for k, p in (("v21", a.v21), ("control", a.control), ("k3", a.k3), ("final", a.final))}
    results = {k: v for k, v in results.items() if v}
    training = load(a.results) or {}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w").write(build(results, training))
    print(f"wrote {a.out} ({os.path.getsize(a.out) // 1024} KB)")


if __name__ == "__main__":
    main()
