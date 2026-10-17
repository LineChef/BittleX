"""The high-step creep plan's final report (phase_hs.py writes trained/hs_report/report.html with it; publish that page as an Artifact).

    ../../.venv/bin/python hs_report.py        # rebuild the page from what is on disk (also works part-way through the plan)
"""
import html as H
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = "trained/hs_report"
MM_TO_IN = 1 / 25.4


def _j(path):
    return json.load(open(path)) if os.path.exists(path) else None


def _inch(mm):
    return f"{mm * MM_TO_IN:.2f} in"


def _clock(t):
    return time.strftime("%b %d %I:%M %p", time.localtime(t)) if t else "-"


def build(st=None):
    import phase_hs as P
    st = st if st is not None else P.load_state()
    v6 = _j(f"{REPORT_DIR}/v6_baseline.json")
    base = _j(f"{REPORT_DIR}/base.json")
    fin = _j(f"{REPORT_DIR}/final.json")
    rows = [("V6 (deployed walk, 0.10 m/s)", v6), ("Creep base, open loop (no policy)", base)]
    for name, *_ in P.STAGES:
        tag = st.get("stages", {}).get(name, {}).get("tag")
        if tag:
            rows.append((f"Stage {name.upper()} ({tag})", _j(f"{REPORT_DIR}/{tag}.json")))
    if fin:
        rows.append((f"Final candidate ({st.get('picked', '?')} of the 20M)", fin))
    rows = [(n, r) for n, r in rows if r]
    sizes = [L["size_mm"] for L in (fin or base or v6 or {"ledges": []})["ledges"]]

    def cellv(r, mm, key):
        L = next((x for x in r["ledges"] if abs(x["size_mm"] - mm) < 1e-6), None)
        return "-" if L is None else f"{L[key]:.2f}"

    head = "".join(f"<th>{mm:g} mm<br><span class='mut'>{_inch(mm)}</span></th>" for mm in sizes)
    lad = {k: "".join(f"<tr><td>{H.escape(n)}</td>" + "".join(f"<td>{cellv(r, mm, k)}</td>" for mm in sizes) + "</tr>" for n, r in rows)
           for k in ("success", "all_up", "falls")}
    flat = ""
    for n, r in rows:
        f = r["flat"] or {}
        g = lambda k, s="{:.1f}": (s.format(f[k]) if f.get(k) is not None else "-")      # noqa: E731
        flat += (f"<tr><td>{H.escape(n)}</td><td>{g('falls', '{:.2f}')}</td><td>{g('speed', '{:.3f}')}</td><td>{g('heading_abs_deg', '{:.0f}')}</td>"
                 f"<td>{g('front_lift_mm')} <span class='mut'>({(f.get('front_lift_mm') or 0) * MM_TO_IN:.2f} in)</span></td>"
                 f"<td>{g('rear_lift_mm')} <span class='mut'>({(f.get('rear_lift_mm') or 0) * MM_TO_IN:.2f} in)</span></td>"
                 f"<td>{g('body_mm')}</td><td>{g('rear_knee_deg', '{:+.1f}')}</td><td>{g('roll_sd_deg')}</td><td>{r.get('ceiling80_mm', 0):g} mm</td></tr>")
    crit = ""
    if fin and v6:
        for text, ok, val in P.verdict(fin, v6):
            crit += f"<tr><td>{H.escape(text)}</td><td class='{'ok' if ok else 'no'}'>{'met' if ok else 'not met'}</td><td>{H.escape(val)}</td></tr>"
    curve = ""
    cpath = f"trained/{P.TAG(P.FINAL[0])}_curve.jsonl"
    if os.path.exists(cpath):
        for l in open(cpath):
            r = json.loads(l)
            f = r["flat"]
            curve += (f"<tr><td>{r['step'] // 10**6}M</td><td>{f['falls']:.2f}</td><td>{(f.get('rear_lift_mm') or 0):.1f}</td>"
                      + "".join(f"<td>{L['success']:.2f} / {L['falls']:.2f}</td>" for L in r["ledges"]) + "</tr>")
    chead = "".join(f"<th>{L['size_mm']:g} mm</th>" for L in json.loads(open(cpath).readline())["ledges"]) if curve else ""
    dec = "".join(f"<li>{H.escape(l[2:])}</li>" for l in open(P.DECISIONS).read().splitlines() if l.startswith("- ")) if os.path.exists(P.DECISIONS) else ""
    sw = _j(f"{REPORT_DIR}/sweep.json")
    sweep_txt = ""
    if sw and sw.get("winner"):
        n_pass = sum(1 for r in sw["round_a"] if r["passes"])
        sweep_txt = (f"<p>Base sweep: {len(sw['round_a'])} candidates played open loop; {n_pass} passed the flat-ground gates (no falls, rear lift at least 3x V6's, body and rear knee at "
                     f"V6's). Winner: <code>{H.escape(json.dumps(sw['winner']['params']))}</code>.</p>")
    times = (f"<p class='mut'>Started {_clock(st.get('started'))}; 20M started {_clock(st.get('final_started'))}, finished {_clock(st.get('final_finished'))}; "
             f"plan complete {_clock(st.get('complete'))}.</p>")
    cand = (f"<p>Exported candidate: <code>{P.CAND_ONNX}</code> (+ <code>.onnx.json</code>: modes [hi_step], base_ref creep, cadence 0.035). Source: <code>{H.escape(str(st.get('picked_path', '')))}</code>. "
            "Not promoted and not deployed: that is your call.</p>") if fin else "<p>No final candidate yet.</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>High-Step Creep Report</title>
<style>:root{{--bg:#fafaf7;--fg:#1d1d1b;--mut:#6b6b64;--line:#dcdcd2;--card:#fff;--ok:#1f7a3a;--no:#a3361f}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#161614;--fg:#ecece6;--mut:#a3a39a;--line:#34342f;--card:#1f1f1c;--ok:#6fcf8a;--no:#ef8a72}}}}
:root[data-theme="dark"]{{--bg:#161614;--fg:#ecece6;--mut:#a3a39a;--line:#34342f;--card:#1f1f1c;--ok:#6fcf8a;--no:#ef8a72}}
body{{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0 auto;padding:24px 16px;max-width:1000px}}h1{{font-size:1.5rem}}h2{{font-size:1.1rem;margin-top:1.8rem}}
.t{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:.86rem;background:var(--card)}}th,td{{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
th{{color:var(--mut);font-weight:600}}.mut{{color:var(--mut)}}.ok{{color:var(--ok);font-weight:600}}.no{{color:var(--no);font-weight:600}}li{{margin:.35rem 0}}code{{font-size:.85em}}</style></head><body>
<h1>High-Step Creep Report</h1>
<p>A separate, slow gait with three feet down at all times, trained to step UP onto ledges (never down). Clearance first; stability is not ranked, but it must not fall on flat ground.
Every number is from the simulator. Step-up success = not fallen, all four paws on the top surface, and the body at least 0.10 m past the edge within 15 s.</p>
{cand}{times}
<h2>Success criteria (set before the run)</h2><div class="t"><table><tr><th>Criterion</th><th>Result</th><th>Value</th></tr>{crit or '<tr><td colspan=3>not scored yet</td></tr>'}</table></div>
<h2>Step-up success</h2><div class="t"><table><tr><th>Policy</th>{head}</tr>{lad['success']}</table></div>
<h2>All four paws up (share of episodes)</h2><div class="t"><table><tr><th>Policy</th>{head}</tr>{lad['all_up']}</table></div>
<h2>Falls on the step-ups</h2><div class="t"><table><tr><th>Policy</th>{head}</tr>{lad['falls']}</table></div>
<h2>Flat ground (calm 20 s walks)</h2><div class="t"><table><tr><th>Policy</th><th>Falls</th><th>Speed m/s</th><th>Heading deg</th><th>Front lift mm</th><th>Rear lift mm</th><th>Body mm</th><th>Rear knee deg</th><th>Roll sd deg</th><th>80% ceiling</th></tr>{flat}</table></div>
<h2>The 20M as it trained (10 walks, 10 episodes per size)</h2><div class="t"><table><tr><th>Step</th><th>Flat falls</th><th>Rear lift mm</th>{chead}</tr>{curve or '<tr><td>-</td></tr>'}</table></div>
{sweep_txt}
<h2>Decisions made while you were away</h2><ul>{dec}</ul>
<p class="mut">Plan and rules: docs/archive/plan-detail/high-step-creep-training-plan.md. Runner: rl_training/opencat-gym/phase_hs.py; scorer: hs_probe.py; base gait: reference_gait/build_creep_reference.py.</p>
</body></html>"""


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    open(f"{REPORT_DIR}/report.html", "w").write(build())
    print(f"wrote {REPORT_DIR}/report.html")
