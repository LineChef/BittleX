"""The V5 benchmark report (user, 2026-10-09): the new policy against the SCRIPTED walk only (V3 / V4 left out), with plain-language summary sections on top that say
what improved, what got worse, how far training got on each hazard and by how much things changed, and every statistic kept underneath.

    python report_v5.py POLICY_JSON SCRIPTED_JSON OUT_HTML [--frontier trained/<tag>_frontier.json] [--title ...] [--console trained/<tag>_console.log]

POLICY_JSON / SCRIPTED_JSON are benchmark_v5.run_all results (same seeds, so every comparison is paired). A difference is "significant" when the exact paired test on the
falls (McNemar) is below 0.05 AFTER the Holm correction over every compared cell (29+ cells at a plain 0.05 would flag about 1.5 cells by chance)."""
import argparse
import html
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paired_compare import mcnemar  # noqa: E402

FLAT = ("T1.1", "N1", "N2", "L1")
NOTICE = 0.05          # a fall-rate change this big is named even when it is not significant
SLOPE_IDS = ("T2.2", "T3.2", "SL10", "SL8", "SR8")     # slope / tilt tests: not a primary trait (user, 2026-10-09)
SLOPE_LARGE = 0.30       # a slope / tilt result only counts against the policy when it falls this much more often than scripted
SIDE_GAP = 0.10        # side-hill left vs right: at most this fall-rate gap counts as even


def holm(ps):
    """Holm-adjusted p-values (same order)."""
    idx = sorted(range(len(ps)), key=lambda i: ps[i])
    out, run = [1.0] * len(ps), 0.0
    for r, i in enumerate(idx):
        run = max(run, min(1.0, (len(ps) - r) * ps[i]))
        out[i] = run
    return out


def compare_cells(P, S):
    """[(id, label, policy cell, scripted cell, diff, adjusted p, verdict)] over every cell both have (T / N / V5 cells and the size ladder)."""
    rows = []
    for a in P:
        b = S.get(a["id"])
        if b is None or "ep_fell" not in a or "ep_fell" not in b:
            continue
        p, n10, n01 = mcnemar(b["ep_fell"], a["ep_fell"])
        rows.append([a["id"], a.get("label") or a["id"], a, b, a["fell_fraction"] - b["fell_fraction"], p])
    adj = holm([r[5] for r in rows])
    out = []
    for r, q in zip(rows, adj):
        d = r[4]
        if q < 0.05:
            v = "Better" if d < 0 else "Worse"
        elif abs(d) >= NOTICE:
            v = "Slightly better" if d < 0 else "Slightly worse"
        else:
            v = "Same"
        out.append(dict(id=r[0], label=r[1], p=r[2], s=r[3], diff=d, padj=q, verdict=v, sig=q < 0.05))
    return out


def ladder_label(c):
    import benchmark_v5 as B
    label, unit, k, _ = B.LADDER[c["hazard"]]
    return f"{label}, {fmt_size(c['size'], unit, k)} (7.5 s)"


def fmt_size(v, unit, k):
    if v is None:
        return "none"
    x = v * k
    return f"{x:.0f} {unit}" if unit == "mm" else (f"{x:.1f}".rstrip("0").rstrip(".") + (" deg" if unit == "deg" else " x level-1"))


def trained_to(frontier, h):
    """'trained up to X' from a run's frontier state (the bin it reached and any ceiling it found)."""
    import benchmark_v5 as B
    if not frontier or h not in frontier.get("F", {}):
        return "not tracked"
    K, F, bound = frontier["n_bins"], frontier["F"][h], frontier["bound"][h]
    _, unit, k, _ = B.LADDER[h]
    txt = f"up to {fmt_size((F + 1) / K * bound, unit, k)} (level {F + 1} of {K})"
    if frontier.get("blocked", {}).get(h) is not None:
        txt += f"; could not pass {fmt_size(frontier['blocked'][h] / K * bound, unit, k)}"
    return txt


def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def pts(d):
    n = round(abs(d) * 100)
    if n == 0:
        return "no change in falls"
    return f"{n} point{'s' if n != 1 else ''} {'fewer' if d < 0 else 'more'} falls"


def build(P, S, frontier=None, title="G2 Gait V5 vs Scripted", console=None, policy_name="V5"):
    import benchmark_v5 as B
    Pc = {c["id"]: c for c in P["cells"]}
    Sc = {c["id"]: c for c in S["cells"]}
    Pl = {c["id"]: c for c in P.get("size_ladder", {}).get("cells", [])}
    Sl = {c["id"]: c for c in S.get("size_ladder", {}).get("cells", [])}
    for c in Pl.values():
        c["label"] = ladder_label(c) if c["hazard"] else "Hazard-free walk (7.5 s)"
    cmp_cells = compare_cells(list(Pc.values()), Sc)
    cmp_lad = compare_cells(list(Pl.values()), Sl)
    allcmp = cmp_cells + cmp_lad
    PS, SS = P["size_ladder"]["summary"], S["size_ladder"]["summary"]

    # ---- verdict on the win criteria (docs/plan-detail/v5-training-plan.md section 6)
    crit = []
    flat_falls = {c: Pc[c]["fell_fraction"] for c in FLAT if c in Pc}
    ok = all(v == 0 for v in flat_falls.values())
    crit.append(("No falls on flat ground", ok, "No falls in the calm, long and endurance walks." if ok else
                 "It fell on flat ground: " + ", ".join(f"{c} {v:.0%}" for c, v in flat_falls.items() if v > 0) + "."))
    haz = [r for r in allcmp if r["id"] not in FLAT and not r["id"].startswith("N") and r["id"] != "Z0"]
    mp, ms = (sum(r["p"]["fell_fraction"] for r in haz) / max(1, len(haz)), sum(r["s"]["fell_fraction"] for r in haz) / max(1, len(haz)))
    worse_sig = [r for r in haz if r["verdict"] == "Worse" and not (r["id"] in SLOPE_IDS and r["p"]["fell_fraction"] - r["s"]["fell_fraction"] < SLOPE_LARGE)]
    ok = mp < ms and not worse_sig
    crit.append(("Fewer hazard falls than scripted, no hazard significantly worse", ok,
                 f"Across {len(haz)} hazard tests it falls {mp:.0%} of the time against scripted's {ms:.0%} ({pts(mp - ms)})" +
                 (f"; significantly worse on {', '.join(r['label'] for r in worse_sig)}." if worse_sig else "; no hazard is significantly worse.")))
    gl, gr = PS.get("sidehill_l"), PS.get("sidehill_r")
    side_ok, side_txt = None, "side-hill ladder missing"
    if gl and gr:
        gap = abs(gl["mean_falls"] - gr["mean_falls"])
        s8 = (Pc.get("SL8", {}).get("fell_fraction"), Pc.get("SR8", {}).get("fell_fraction"))
        gap8 = abs(s8[0] - s8[1]) if None not in s8 else 0.0
        side_ok = gap <= SIDE_GAP and gap8 <= SIDE_GAP and gl["largest_passed"] == gr["largest_passed"]
        side_txt = (f"Left side down: falls {gl['mean_falls']:.0%} over the ladder, passes up to {fmt_size(gl['largest_passed'], 'deg', 1)}; right side down: "
                    f"{gr['mean_falls']:.0%}, up to {fmt_size(gr['largest_passed'], 'deg', 1)}. At 8 deg (3.1 s): left {s8[0] if s8[0] is None else f'{s8[0]:.0%}'}, "
                    f"right {s8[1] if s8[1] is None else f'{s8[1]:.0%}'}. " + ("Even." if side_ok else "Not even."))
    crit.append(("Side-hills even in both directions (for information, not scored)", side_ok, side_txt))
    n1p, n1s = Pc.get("N1"), Sc.get("N1")
    if n1p and n1s:
        ok = (n1p["roll_std_deg"] <= 1.1 * n1s["roll_std_deg"] and n1p["heading_abs_mean_deg"] <= n1s["heading_abs_mean_deg"] + 3.0)
        crit.append(("Calm walk at least as smooth and straight as scripted", ok,
                     f"12.5 s calm walk: roll sway {n1p['roll_std_deg']:.1f} deg vs scripted {n1s['roll_std_deg']:.1f}; heading change {n1p['heading_abs_mean_deg']:.0f} deg vs "
                     f"{n1s['heading_abs_mean_deg']:.0f}; speed {n1p['path_speed_mps']:.3f} vs {n1s['path_speed_mps']:.3f} m/s."))
    scored = [c for c in crit if "not scored" not in c[0]]
    passed = sum(1 for c in scored if c[1])
    headline = (f"{policy_name} meets {passed} of {len(scored)} win criteria against the scripted walk. "
                f"{sum(r['verdict'] == 'Better' for r in allcmp)} tests significantly better, {sum(r['verdict'] == 'Worse' for r in allcmp)} significantly worse, "
                f"{sum(r['verdict'] in ('Slightly better', 'Slightly worse') for r in allcmp)} changed a little, {sum(r['verdict'] == 'Same' for r in allcmp)} the same.")

    # ---- per-hazard summary rows
    hz_rows = []
    for h, (label, unit, k, sizes) in B.LADDER.items():
        a, b = PS.get(h), SS.get(h)
        if not a or not b:
            continue
        top_p, top_s = a["largest_passed"], b["largest_passed"]
        d = a["mean_falls"] - b["mean_falls"]
        lad = [r for r in cmp_lad if Pl.get(r["id"], {}).get("hazard") == h]
        sig_b = [r for r in lad if r["verdict"] == "Better"]
        sig_w = [r for r in lad if r["verdict"] == "Worse"]
        verdict = "Better" if (sig_b and not sig_w) else "Worse" if (sig_w and not sig_b) else "Mixed" if (sig_b and sig_w) else (
            "Slightly better" if d <= -NOTICE else "Slightly worse" if d >= NOTICE else "Same")
        rank = lambda t: -1 if t is None else sizes.index(t) if t in sizes else -1
        if rank(top_p) > rank(top_s):
            size_txt = f"passes bigger sizes than scripted ({fmt_size(top_p, unit, k)} vs {fmt_size(top_s, unit, k)})"
        elif rank(top_p) < rank(top_s):
            size_txt = f"passes smaller sizes than scripted ({fmt_size(top_p, unit, k)} vs {fmt_size(top_s, unit, k)})"
        else:
            size_txt = f"passes the same sizes as scripted (up to {fmt_size(top_p, unit, k)})"
        cross = ""
        if h in B.OBJECT_HAZARDS:
            ca = [x for x in a["past_all"] if x is not None]
            cb = [x for x in b["past_all"] if x is not None]
            if ca and cb:
                cross = f" Gets past the whole field {sum(ca) / len(ca):.0%} of the time (scripted {sum(cb) / len(cb):.0%})."
        if h in B.LEDGE_HAZARDS:
            ca, cb = a["past_ledge"], b["past_ledge"]
            cross = f" Gets over the edge {sum(ca) / len(ca):.0%} of the time (scripted {sum(cb) / len(cb):.0%})."
        sentence = f"{label}: {size_txt}; falls {a['mean_falls']:.0%} vs {b['mean_falls']:.0%} averaged over the four sizes ({pts(d)}).{cross}"
        hz_rows.append(dict(h=h, label=label, trained=trained_to(frontier, h), top_p=fmt_size(top_p, unit, k), top_s=fmt_size(top_s, unit, k),
                            falls=f"{a['mean_falls']:.0%} vs {b['mean_falls']:.0%}", change=(f"{-d * 100:+.0f} pts" if abs(d) >= 0.005 else "0"), verdict=verdict, sentence=sentence))

    # ---- better / worse / unchanged, in sentences
    def line(r):
        a, b = r["p"], r["s"]
        sig = " (significant)" if r["sig"] else ""
        return f"{r['label']}: falls {a['fell_fraction']:.0%} vs scripted {b['fell_fraction']:.0%}, {pts(r['diff'])}{sig}."
    better = [line(r) for r in sorted(allcmp, key=lambda r: r["diff"]) if r["verdict"] in ("Better", "Slightly better")]
    worse = [line(r) for r in sorted(allcmp, key=lambda r: -r["diff"]) if r["verdict"] in ("Worse", "Slightly worse")]
    same = [r["label"] for r in allcmp if r["verdict"] == "Same"]

    # ---- symmetry and flat-ground quality
    sym = []
    if n1p and n1s:
        sym.append(f"Calm walk (12.5 s): left-right joint difference {n1p['lr_asym_max_deg']:.1f} deg (scripted {n1s['lr_asym_max_deg']:.1f}); heading change "
                   f"{n1p['heading_mean_deg']:+.0f} deg on average, {n1p['heading_abs_mean_deg']:.0f} deg either way (scripted {n1s['heading_mean_deg']:+.0f} / "
                   f"{n1s['heading_abs_mean_deg']:.0f}); roll sway {n1p['roll_std_deg']:.1f} deg (scripted {n1s['roll_std_deg']:.1f}); pitch sway {n1p['pitch_std_deg']:.1f} deg "
                   f"(scripted {n1s['pitch_std_deg']:.1f}).")
    if "L1" in Pc:
        sym.append(f"Long 40 s walk with alternating sideways pushes: heading change {Pc['L1']['heading_even_abs_mean_deg']:.0f} deg when pushed right, "
                   f"{Pc['L1']['heading_odd_abs_mean_deg']:.0f} deg when pushed left (gap {Pc['L1']['heading_sign_gap_deg']:.0f} deg; scripted {Sc.get('L1', {}).get('heading_sign_gap_deg', float('nan')):.0f}).")
    if P.get("mirror_gap") is not None:
        sym.append(f"Mirror gap (how differently it answers a left-right mirrored situation; 0 = perfectly symmetric): {P['mirror_gap']:.3f}.")
    for a, b, nm in (("SL10", "T3.2", "10 deg side-hill (3.1 s)"), ("SL8", "SR8", "8 deg side-hill (3.1 s)")):
        if a in Pc and b in Pc:
            sym.append(f"{nm}: left side down falls {Pc[a]['fell_fraction']:.0%}, right side down {Pc[b]['fell_fraction']:.0%} (scripted {Sc[a]['fell_fraction']:.0%} / {Sc[b]['fell_fraction']:.0%}).")
    sym.append(side_txt)

    # ---- training summary (optional)
    train_txt = ""
    if console and os.path.exists(console):
        lines = open(console, errors="replace").read().splitlines()
        ev = [(int(m.group(1)), float(m.group(2))) for l in lines for m in [re.search(r"^\[health\] steps (\d+)\s+eval ([0-9.]+)", l)] if m]
        stop = next((l for l in lines if l.startswith("[plateau]")), None)
        if ev:
            train_txt = (f"Health eval (fixed hazard course, 1 = no worse than a calm walk) went {ev[0][1]:.2f} at {ev[0][0] / 1e6:.0f}M to {ev[-1][1]:.2f} at {ev[-1][0] / 1e6:.0f}M"
                         f" (best {max(v for _, v in ev):.2f}). " + (f"Stopped early by the plateau rule: {stop.split(':', 1)[1].strip()}" if stop else ""))

    return _html(title, headline, crit, hz_rows, better, worse, same, sym, train_txt, cmp_cells, cmp_lad, P, S, frontier, policy_name)


def _e(x):
    return html.escape(str(x))


def _html(title, headline, crit, hz_rows, better, worse, same, sym, train_txt, cmp_cells, cmp_lad, P, S, frontier, name):
    css = """
:root{--bg:#f4f5f2;--panel:#fff;--ink:#17201c;--ink2:#4c5a53;--rule:#d3d9d5;--good:#1d7a45;--goodbg:#ddf1e4;--bad:#b13a2e;--badbg:#f8e0dc;--warn:#8a6514;--warnbg:#f6ecd2;--ref:#e9ece9;--accent:#1f6f8b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#101513;--panel:#171e1b;--ink:#e3e9e5;--ink2:#9fb0a7;--rule:#2b3732;--good:#62cf91;--goodbg:#173527;--bad:#f08b7e;--badbg:#3b1f1b;--warn:#e2b55a;--warnbg:#3a2f15;--ref:#1d2622;--accent:#5cc0de}}
:root[data-theme="dark"]{--bg:#101513;--panel:#171e1b;--ink:#e3e9e5;--ink2:#9fb0a7;--rule:#2b3732;--good:#62cf91;--goodbg:#173527;--bad:#f08b7e;--badbg:#3b1f1b;--warn:#e2b55a;--warnbg:#3a2f15;--ref:#1d2622;--accent:#5cc0de}
body{background:var(--bg);color:var(--ink);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:24px 16px 64px}
.wrap{max-width:960px;margin:0 auto;display:flex;flex-direction:column;gap:36px}
h1{font-size:clamp(1.8rem,4vw,2.5rem);margin:0}h2{font-size:1.35rem;margin:0;padding-top:12px;border-top:2px solid var(--ink)}
p,li{max-width:72ch}section{display:flex;flex-direction:column;gap:12px;min-width:0}
.lede{font-size:1.1rem}.card{background:var(--panel);border:1px solid var(--rule);border-radius:4px;padding:16px 18px}
.crit{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;align-items:start}
.tag{font:600 .75rem ui-monospace,Menlo,monospace;padding:2px 8px;border-radius:3px;white-space:nowrap}
.ok{background:var(--goodbg);color:var(--good)}.no{background:var(--badbg);color:var(--bad)}.mid{background:var(--warnbg);color:var(--warn)}
.scroll{overflow-x:auto;border:1px solid var(--rule);border-radius:4px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:.88rem;min-width:640px;font-variant-numeric:tabular-nums}
th,td{padding:6px 9px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}thead th{background:var(--ref);color:var(--ink2);font-weight:600;font-size:.78rem}
td.n{text-align:right;font-family:ui-monospace,Menlo,monospace}.note{color:var(--ink2);font-size:.9rem}
ul{margin:0;padding-left:1.2em;display:flex;flex-direction:column;gap:4px}"""

    def vtag(v):
        cls = "ok" if v in ("Better", "Slightly better") else "no" if v in ("Worse", "Slightly worse") else "mid" if v == "Mixed" else ""
        return f'<span class="tag {cls}">{_e(v)}</span>'

    crit_html = "".join(f'<span class="tag {"ok" if ok else "mid" if ok is None else "no"}">{"PASS" if ok else "n/a" if ok is None else "NOT MET"}</span>'
                        f"<div><b>{_e(n)}.</b> {_e(t)}</div>" for n, ok, t in crit)
    hz_html = "".join(f"<tr><td>{_e(r['label'])}</td><td>{_e(r['trained'])}</td><td>{_e(r['top_p'])}</td><td>{_e(r['top_s'])}</td><td class=n>{_e(r['falls'])}</td>"
                      f"<td class=n>{_e(r['change'])}</td><td>{vtag(r['verdict'])}</td></tr>" for r in hz_rows)
    hz_sent = "".join(f"<li>{_e(r['sentence'])}</li>" for r in hz_rows)
    ul = lambda xs, empty: "<ul>" + ("".join(f"<li>{_e(x)}</li>" for x in xs) if xs else f"<li>{_e(empty)}</li>") + "</ul>"

    def stat_rows(rows):
        out = []
        for r in rows:
            a, b = r["p"], r["s"]
            out.append(f"<tr><td>{_e(r['id'])}</td><td>{_e(r['label'])}</td><td class=n>{a['fell_fraction']:.2f}</td><td class=n>{b['fell_fraction']:.2f}</td>"
                       f"<td class=n>{r['padj']:.3f}</td><td>{vtag(r['verdict'])}</td><td class=n>{a.get('path_speed_mps', 0):.3f}</td><td class=n>{b.get('path_speed_mps', 0):.3f}</td>"
                       f"<td class=n>{a.get('roll_std_deg', 0):.1f}</td><td class=n>{b.get('roll_std_deg', 0):.1f}</td><td class=n>{a.get('heading_mean_deg', 0):+.0f}</td>"
                       f"<td class=n>{b.get('heading_mean_deg', 0):+.0f}</td><td class=n>{a.get('lr_asym_max_deg', 0):.1f}</td><td class=n>{a.get('n', '')}</td></tr>")
        return "".join(out)
    head = ("<thead><tr><th>Cell</th><th>Test</th><th>Falls " + _e(name) + "</th><th>Falls scripted</th><th>p (Holm)</th><th>Verdict</th><th>Path speed " + _e(name) +
            "</th><th>Path speed scripted</th><th>Roll sway " + _e(name) + "</th><th>Roll sway scripted</th><th>Heading " + _e(name) + "</th><th>Heading scripted</th>"
            "<th>L-R joint diff</th><th>Episodes</th></tr></thead>")
    lad_extra = []
    for r in cmp_lad:
        a, b = r["p"], r["s"]
        lad_extra.append(f"<tr><td>{_e(r['label'])}</td><td class=n>{a.get('success', 0):.0%}</td><td class=n>{b.get('success', 0):.0%}</td>"
                         f"<td class=n>{pct(a.get('past_all'))}</td><td class=n>{pct(b.get('past_all'))}</td><td class=n>{pct(a.get('past_ledge'))}</td>"
                         f"<td class=n>{pct(b.get('past_ledge'))}</td><td class=n>{a.get('dist_median_m', 0):.2f}</td><td class=n>{b.get('dist_median_m', 0):.2f}</td></tr>")
    fr_html = ""
    if frontier:
        rows = []
        for h, bins in frontier.get("bins", {}).items():
            cells = " ".join(("-" if m is None else f"{m:.2f}/{n}") for m, n in bins)
            rows.append(f"<tr><td>{_e(h)}</td><td class=n>{frontier['F'][h] + 1}</td><td style='font-family:ui-monospace,Menlo,monospace;font-size:.78rem'>{_e(cells)}</td></tr>")
        fr_html = ("<section><h2>Training curriculum, raw</h2><p class=note>Success rate / episodes at each of the 12 size levels per hazard at the end of training "
                   f"(hazard-free success {frontier.get('anchor', float('nan')):.2f}).</p><div class=scroll><table><thead><tr><th>Hazard</th><th>Level reached</th>"
                   "<th>Success / episodes per level</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></section>")
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>{_e(title)}</title><style>{css}</style></head>
<body><div class=wrap>
<header><h1>{_e(title)}</h1><p class=lede>{_e(headline)}</p><p class=note>Every number compares {_e(name)} with the scripted walk on the same courses (paired seeds). The summary sections
say what the result was; the full statistics are at the bottom.</p></header>
<section><h2>Verdict</h2><div class="card crit">{crit_html}</div>{('<p class=note>' + _e(train_txt) + '</p>') if train_txt else ''}</section>
<section><h2>Per hazard</h2><p class=note>"Trained up to" is how far the curriculum got during training. "Largest size passed" means at most 20% of the 7.5 s episodes fell at that size and every
smaller one. Change = fall-rate points against scripted, averaged over the four sizes (+ = fewer falls).</p>
<div class=scroll><table><thead><tr><th>Hazard</th><th>Trained up to</th><th>Largest passed, {_e(name)}</th><th>Largest passed, scripted</th><th>Falls {_e(name)} vs scripted</th><th>Change</th><th>Verdict</th></tr></thead>
<tbody>{hz_html}</tbody></table></div><ul>{hz_sent}</ul></section>
<section><h2>What got better</h2>{ul(better, "Nothing measurably better than scripted.")}</section>
<section><h2>What got worse</h2>{ul(worse, "Nothing measurably worse than scripted.")}</section>
<section><h2>What did not change</h2><p>{_e(", ".join(same) if same else "Every test changed.")}</p></section>
<section><h2>Symmetry and flat-ground quality</h2><ul>{"".join(f"<li>{_e(s)}</li>" for s in sym)}</ul></section>
<section><h2>All statistics: benchmark cells (3.1 s unless the label says otherwise)</h2><div class=scroll><table>{head}<tbody>{stat_rows(cmp_cells)}</tbody></table></div></section>
<section><h2>All statistics: size ladder (7.5 s)</h2><div class=scroll><table>{head}<tbody>{stat_rows(cmp_lad)}</tbody></table></div>
<div class=scroll><table><thead><tr><th>Ladder cell</th><th>Success {_e(name)}</th><th>Success scripted</th><th>Past whole field {_e(name)}</th><th>Past whole field scripted</th>
<th>Over the edge {_e(name)}</th><th>Over the edge scripted</th><th>Median distance {_e(name)}, m</th><th>Median distance scripted, m</th></tr></thead><tbody>{"".join(lad_extra)}</tbody></table></div></section>
{fr_html}
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("policy_json")
    ap.add_argument("scripted_json")
    ap.add_argument("out_html")
    ap.add_argument("--frontier", default=None)
    ap.add_argument("--console", default=None)
    ap.add_argument("--title", default="G2 Gait V5 vs Scripted")
    ap.add_argument("--name", default="V5")
    a = ap.parse_args()
    P, S = json.load(open(a.policy_json)), json.load(open(a.scripted_json))
    fr = json.load(open(a.frontier)) if a.frontier and os.path.exists(a.frontier) else None
    open(a.out_html, "w").write(build(P, S, fr, a.title, a.console, a.name))
    print(f"wrote {a.out_html}")


if __name__ == "__main__":
    main()
