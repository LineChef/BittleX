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


def build(results, training, title="V3 Pre-20M Benchmark"):
    ref = results.get("v21") or next(iter(results.values()))
    fin = results.get("final")
    meta = (f'benchmark version {ref.get("bench_version", "?")}, {ref.get("episodes", "?")} episodes per cell, seed {ref.get("seed", "?")}'
            + (f', ladder {fin["ladder"]["episodes"]} episodes per rung' if fin and fin.get("ladder") else ""))
    parts = [f"<title>{e(title)}</title>", f"<style>{CSS}</style>",
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">',
             '<div class="page"><header><div class="eyebrow">G2 gait retrain / benchmark before the 20M decision</div>', f"<h1>{e(title)}</h1>",
             f'<p class="lede">Final-stage policy against the deployed V2.1, scored on the training-matched benchmark. {e(meta)}. Generated {time.strftime("%B %d, %Y, %I:%M %p")} Eastern.</p></header>',
             sec_verdict(results), sec_ladder(results), sec_straight(results), sec_cells(results), sec_replicates(training), sec_history(training), sec_caveats(),
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
