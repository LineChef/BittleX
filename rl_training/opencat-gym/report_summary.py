"""The short benchmark report (user, 2026-10-09: "a quick overview of the results without having to compare numbers for myself; I can ask for more granular details").

One page: a verdict sentence, a scorecard of eight topics each with a plain word (Better / About the same / Worse than the reference) and one short sentence, and a small bar of
overall falls. The full statistics report (report_v5.py) is still written next to it as report_full.html and is only shared when asked for.

    build(P, refs, name="V6", primary="V4", verdict_text="...") -> html
P and every refs[name] are benchmark_v5.run_all results (same seeds). `primary` is the policy the topics are judged against; a topic is Better / Worse when its fall rate differs by
NOTICE (5 points) or more, otherwise About the same. Slopes and tilts are marked secondary (user, 2026-10-09)."""
import html
import os

NOTICE = 0.05
TOPICS = [   # (title, cell ids, ladder hazard or None, secondary?)
    ("Calm walking on flat ground", ["T1.1", "T1.2", "L1"], None, False),
    ("Small step-ups (about 7-15 mm)", ["LU15"], "ledge_up:small", False),
    ("Bigger step-ups (25-35 mm)", ["T5.2", "LU25", "LU35"], "ledge_up:big", False),
    ("Step-downs", ["LD15", "LD25", "LD40"], "ledge_down", False),
    ("Rubble, boxes and snags", ["T6.1", "T6.2", "T7.1", "T7.2"], "rubble", False),
    ("Shoves and the hardest course", ["T8.1", "T11.1", "T11.2"], None, False),
    ("Slopes and tilts", ["T2.1", "T2.2", "T3.1", "T3.2", "T4.1", "T4.2", "SL10", "SR8", "SL8"], None, True),
]


def _cells(res):
    return {c["id"]: c for c in res["cells"]}


def _mean(cells, ids):
    v = [cells[i]["fell_fraction"] for i in ids if i in cells]
    return sum(v) / len(v) if v else None


def _word(d):
    return "Better" if d <= -NOTICE else "Worse" if d >= NOTICE else "About the same"


def _ladder_success(res, key):
    s = res.get("size_ladder", {}).get("summary", {})
    hz, _, part = key.partition(":")
    if hz not in s:
        return None
    suc = s[hz]["success"]
    return suc[0] if part == "small" else max(suc[1:]) if part == "big" else sum(suc) / len(suc)


def topic_rows(P, ref, name, refname):
    cp, cr = _cells(P), _cells(ref)
    rows = []
    for k, (title, ids, lad, secondary) in enumerate(TOPICS):
        a, b = _mean(cp, ids), _mean(cr, ids)
        if a is None or b is None:
            continue
        w = _word(a - b)
        if k == 0 and "N1" in cp and "N1" in cr:                      # the calm walk is judged on straightness and sway as well as falls
            n, m = cp["N1"], cr["N1"]
            dh, rs = n["heading_abs_mean_deg"] - m["heading_abs_mean_deg"], n["roll_std_deg"] / max(m["roll_std_deg"], 1e-6)
            w = "Worse" if (a - b) >= NOTICE or dh > 3 or rs > 1.1 else "Better" if (b - a) >= NOTICE or dh < -3 or rs < 0.9 else "About the same"
            fell = "No falls" if a == 0 else f"Falls {a * 100:.0f}% of the time"
            rows.append(dict(title=title, word=w, secondary=secondary, a=a, b=b,
                             text=f"{fell}. Drifts {n['heading_abs_mean_deg']:.0f} deg off straight ({refname} {m['heading_abs_mean_deg']:.0f}), body sway {n['roll_std_deg']:.1f} deg ({refname} {m['roll_std_deg']:.1f})."))
            continue
        pa, pb = round(a * 100), round(b * 100)
        if w == "About the same":
            txt = f"Falls about as often as {refname} ({pa}% against {pb}%)."
        else:
            txt = f"{'Fewer' if w == 'Better' else 'More'} falls than {refname} ({pa}% against {pb}%)."
        if lad and lad.startswith("ledge_up"):
            sa, sb = _ladder_success(P, lad), _ladder_success(ref, lad)
            if sa is not None and sb is not None:
                if lad.endswith("small"):
                    txt += f" Gets up the smallest ledge {sa:.0%} of the time ({refname} {sb:.0%})."
                elif max(sa, sb) == 0:
                    txt += f" Neither gets over a ledge this big."
                else:
                    txt += f" Gets over {sa:.0%} of the big ones ({refname} {sb:.0%})."
        rows.append(dict(title=title, word=w, text=txt, secondary=secondary, a=a, b=b))
    return rows


def overall(P, refs, ids=None):
    cp = _cells(P)
    ids = ids or [i for i in cp if not i.startswith(("Z.", "N")) and i != "Z0" and all(i in _cells(r) for r in refs.values())]
    return {"this": _mean(cp, ids), **{n: _mean(_cells(r), ids) for n, r in refs.items()}}, ids


def build(P, refs, name="V6", primary="V4", verdict_text="", title=None):
    title = title or f"{name} benchmark, short version"
    rows = topic_rows(P, refs[primary], name, primary)
    ov, ids = overall(P, refs)
    core = [r for r in rows if not r["secondary"]]
    better, worse = [r for r in core if r["word"] == "Better"], [r for r in core if r["word"] == "Worse"]
    head = (f"Against {primary}: better on {len(better)} of {len(core)} main topics, worse on {len(worse)}, about the same on the rest. "
            + (f"Better: {', '.join(r['title'].lower() for r in better)}. " if better else "") + (f"Worse: {', '.join(r['title'].lower() for r in worse)}." if worse else ""))
    e = html.escape
    chip = lambda w: f'<span class="chip {"ok" if w == "Better" else "no" if w == "Worse" else "mid"}">{e(w)}</span>'      # noqa: E731
    trs = "".join(f'<div class="row"><div>{chip(r["word"])}</div><div><b>{e(r["title"])}</b>{" <i>(secondary)</i>" if r["secondary"] else ""}<br><span class="note">{e(r["text"])}</span></div></div>'
                  for r in rows)
    mx = max(v for v in ov.values() if v is not None) or 1
    bars = "".join(f'<div class="bar"><span class="lab">{e(n if n != "this" else name)}</span><span class="track"><span class="fill {"me" if n == "this" else ""}" '
                   f'style="width:{v / mx * 100:.0f}%"></span></span><span class="val">{v:.0%}</span></div>' for n, v in ov.items() if v is not None)
    css = """:root{--bg:#f4f5f2;--panel:#fff;--ink:#17201c;--ink2:#4c5a53;--rule:#d3d9d5;--good:#1d7a45;--goodbg:#ddf1e4;--bad:#b13a2e;--badbg:#f8e0dc;--warn:#8a6514;--warnbg:#f6ecd2;--accent:#1f6f8b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#101513;--panel:#171e1b;--ink:#e3e9e5;--ink2:#9fb0a7;--rule:#2b3732;--good:#62cf91;--goodbg:#173527;--bad:#f08b7e;--badbg:#3b1f1b;--warn:#e2b55a;--warnbg:#3a2f15;--accent:#5cc0de}}
:root[data-theme="dark"]{--bg:#101513;--panel:#171e1b;--ink:#e3e9e5;--ink2:#9fb0a7;--rule:#2b3732;--good:#62cf91;--goodbg:#173527;--bad:#f08b7e;--badbg:#3b1f1b;--warn:#e2b55a;--warnbg:#3a2f15;--accent:#5cc0de}
body{background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:24px 16px 56px}
.wrap{max-width:760px;margin:0 auto;display:flex;flex-direction:column;gap:24px}h1{font-size:clamp(1.6rem,4vw,2.2rem);margin:0}h2{font-size:1.15rem;margin:0 0 8px}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:4px;padding:14px 16px}.note{color:var(--ink2);font-size:.92rem}
.row{display:grid;grid-template-columns:7.5em 1fr;gap:10px;padding:9px 0;border-bottom:1px solid var(--rule)}.row:last-child{border:0}
.chip{font:600 .78rem ui-monospace,Menlo,monospace;padding:3px 8px;border-radius:3px;white-space:nowrap}.ok{background:var(--goodbg);color:var(--good)}.no{background:var(--badbg);color:var(--bad)}.mid{background:var(--warnbg);color:var(--warn)}
.bar{display:grid;grid-template-columns:5.5em 1fr 3em;gap:8px;align-items:center;margin:5px 0}.track{background:var(--rule);height:14px;border-radius:2px;overflow:hidden}.fill{display:block;height:100%;background:var(--ink2)}.fill.me{background:var(--accent)}.val{text-align:right;font-variant-numeric:tabular-nums}"""
    return (f'<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>{e(title)}</title><style>{css}</style></head>'
            f'<body><div class=wrap><header><h1>{e(title)}</h1><p>{e(head)}</p>{("<p><b>" + e(verdict_text) + "</b></p>") if verdict_text else ""}</header>'
            f'<section class=card><h2>Topic by topic, against {e(primary)}</h2>{trs}</section>'
            f'<section class=card><h2>Overall falls</h2><p class=note>Share of test walks that ended in a fall, averaged over {len(ids)} hazard tests (shorter bar = fewer falls).</p>{bars}</section>'
            f'<p class=note>Ask for the detailed statistics, cell by cell or with significance tests, and I will share the full report.</p></div></body></html>')
