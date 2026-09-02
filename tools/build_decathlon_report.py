"""Turn a decathlon.json + gif dir into a self-contained HTML report.

    python build_decathlon_report.py decathlon.json gifs/ out.html [label]
"""
import base64
import json
import sys
from pathlib import Path

J, GIFDIR, OUT = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
LABEL = sys.argv[4] if len(sys.argv) > 4 else "learned gait"
d = json.load(open(J))
cells = d["cells"]

# metric -> (pretty, higher_is_better, fmt, tie_margin)
M = {
    "fell_fraction":            ("fall rate",       False, lambda v: f"{v:.0%}",  0.06),
    "forward_speed_mps_mean":   ("speed m/s",       True,  lambda v: f"{v:.3f}",  0.008),
    "forward_distance_m_mean":  ("distance m",      True,  lambda v: f"{v:.2f}",  0.03),
    "diagonal_trot_corr_mean":  ("trot |corr|",     True,  lambda v: f"{abs(v):.2f}", 0.06),
    "yaw_rate_rms_deg_mean":    ("yaw-rate rms deg",False, lambda v: f"{v:.1f}",  1.5),
    "lat_offset_max_m_mean":    ("lateral drift m", False, lambda v: f"{v:.3f}",  0.02),
    "big_stumble_recovery_rate":("stumbles caught", True,  lambda v: f"{v:.0%}",  0.10),
}


def cmp(metric, lv, sv):
    if lv is None or sv is None:
        return "na"
    pretty, hib, fmt, tie = M[metric]
    a, b = (lv, sv)
    delta = a - b if hib else b - a          # >0 => learned better
    if abs(a - b) <= tie:
        return "tie"
    return "win" if delta > 0 else "loss"


def trot(v):
    return abs(v) if v is not None else None


# ---- aggregate verdict ----
wins = losses = ties = 0
for c in cells:
    for m in M:
        r = cmp(m, c["learned"][m], c["scripted"][m])
        wins += r == "win"; losses += r == "loss"; ties += r == "tie"
fell_l = sum(c["learned"]["fell_fraction"] for c in cells) / len(cells)
fell_s = sum(c["scripted"]["fell_fraction"] for c in cells) / len(cells)
spd_l = sum(c["learned"]["forward_speed_mps_mean"] for c in cells) / len(cells)
spd_s = sum(c["scripted"]["forward_speed_mps_mean"] for c in cells) / len(cells)
tot_sc = sum(c["scripted_fall_episodes"] for c in cells)
tot_sv = sum(round((c["conditional_survival"] or 0) * c["scripted_fall_episodes"]) for c in cells)
pooled_cs = (tot_sv / tot_sc) if tot_sc else None

if fell_s - fell_l > 0.05:
    head = (f"On this ladder the {LABEL} falls less than the scripted gait "
            f"({fell_l:.0%} vs {fell_s:.0%} averaged over 15 cells) and it can recover from "
            f"stumbles the scripted gait cannot"
            + (f" -- it stayed up on {pooled_cs:.0%} of the courses where scripted fell." if pooled_cs is not None else "."))
elif fell_l - fell_s > 0.05:
    head = (f"On this ladder the scripted gait is the more reliable one "
            f"({fell_s:.0%} falls vs the {LABEL}'s {fell_l:.0%}). The learned gait's edge is "
            f"in stumble recovery, not raw fall rate.")
else:
    head = (f"On this ladder the two gaits fall at about the same rate "
            f"({fell_l:.0%} learned vs {fell_s:.0%} scripted). What separates them is "
            f"where each one breaks and whether it can get back up.")

# ---- per-tier fall rate for the chart ----
tiers = sorted({c["tier"] for c in cells})
tier_fall = {t: (
    sum(c["learned"]["fell_fraction"] for c in cells if c["tier"] == t) / sum(1 for c in cells if c["tier"] == t),
    sum(c["scripted"]["fell_fraction"] for c in cells if c["tier"] == t) / sum(1 for c in cells if c["tier"] == t),
) for t in tiers}
TIER_NAME = {1: "baseline", 2: "moderate terrain", 3: "hard terrain", 4: "disturbance", 5: "everything"}


def bars_svg():
    W, rowh, pad, bw = 560, 46, 130, 190
    H = pad + rowh * len(tiers) + 30
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="fall rate by difficulty tier">']
    parts.append(f'<text x="0" y="16" class="cap">fall rate by difficulty tier &mdash; '
                 f'<tspan fill="var(--accent)">{LABEL}</tspan> vs <tspan fill="var(--muted-strong)">scripted</tspan></text>')
    for i, t in enumerate(tiers):
        y = pad + i * rowh
        lf, sf = tier_fall[t]
        parts.append(f'<text x="0" y="{y+14}" class="tl">T{t} {TIER_NAME[t]}</text>')
        parts.append(f'<rect x="{bw*0+ -0 +0}" y="{y}" width="0" height="0"/>')
        parts.append(f'<rect x="{130}" y="{y}"    width="{max(2,lf* bw):.0f}" height="14" rx="2" fill="var(--accent)"/>')
        parts.append(f'<text x="{130+max(2,lf*bw)+6:.0f}" y="{y+12}" class="v">{lf:.0%}</text>')
        parts.append(f'<rect x="{130}" y="{y+18}" width="{max(2,sf* bw):.0f}" height="14" rx="2" fill="var(--muted-strong)"/>')
        parts.append(f'<text x="{130+max(2,sf*bw)+6:.0f}" y="{y+30}" class="v">{sf:.0%}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---- skill-by-skill ----
def skill_rows():
    skills = {}
    for c in cells:
        skills.setdefault(c["skill"], []).append(c)
    rows = []
    for sk, cs in skills.items():
        lf = sum(c["learned"]["fell_fraction"] for c in cs) / len(cs)
        sf = sum(c["scripted"]["fell_fraction"] for c in cs) / len(cs)
        ls = sum(c["learned"]["forward_speed_mps_mean"] for c in cs) / len(cs)
        ss = sum(c["scripted"]["forward_speed_mps_mean"] for c in cs) / len(cs)
        # did learned fall on strictly fewer cells, and catch scripted's falls?
        l_never = all(c["learned"]["fell_fraction"] < 0.01 for c in cs)
        s_fell_some = any(c["scripted"]["fell_fraction"] > 0.01 for c in cs)
        css = [c["conditional_survival"] for c in cs if c["conditional_survival"] is not None]
        if sf - lf > 0.04 or (l_never and s_fell_some):
            note = f"learned falls less ({lf:.0%} vs {sf:.0%})"
            if css:
                note += f", catches {sum(css)/len(css):.0%} of scripted's"
            verdict, cls = note, "win"
        elif lf - sf > 0.04:
            verdict, cls = f"scripted falls less ({sf:.0%} vs {lf:.0%})", "loss"
        elif ss - ls > 0.005:
            verdict, cls = f"~tie on falls; scripted {(ss-ls)/ss*100:.0f}% faster ({ss:.03f} vs {ls:.03f} m/s)", "loss"
        elif ls - ss > 0.005:
            verdict, cls = f"~tie on falls; learned {(ls-ss)/ss*100:.0f}% faster ({ls:.03f} vs {ss:.03f} m/s)", "win"
        else:
            verdict, cls = "genuine tie", "tie"
        rows.append((sk, len(cs), verdict, cls))
    return rows


def scorecard():
    rows = []
    for c in cells:
        tds = [f'<td class="cid">{c["id"]}</td><td class="lbl">{c["label"]}</td>']
        for m in M:
            lv, sv = c["learned"][m], c["scripted"][m]
            if m == "diagonal_trot_corr_mean":
                lv, sv = trot(lv), trot(sv)
            r = cmp("diagonal_trot_corr_mean" if m == "diagonal_trot_corr_mean" else m,
                    c["learned"][m], c["scripted"][m])
            if lv is None:
                tds.append('<td class="na">&ndash;</td>')
            else:
                fmt = M[m][2]
                tds.append(f'<td class="{r}">{fmt(lv)}<span class="s">{fmt(sv)}</span></td>')
        cs = c["conditional_survival"]
        tds.append(f'<td class="cs">{(f"{cs:.0%}" if cs is not None else "&ndash;")}'
                   f'<span class="s">/{c["scripted_fall_episodes"]}</span></td>')
        rows.append(f'<tr data-tier="{c["tier"]}">' + "".join(tds) + "</tr>")
    return "\n".join(rows)


def b64(name):
    fp = GIFDIR / name
    if not fp.exists():
        return None
    return "data:image/gif;base64," + base64.b64encode(fp.read_bytes()).decode()


def gif_block():
    out = []
    for tag, title in (("easy", "Flat, calm"), ("hard", "Obstacles + shoves"), ("brutal", "The gauntlet")):
        l, s = b64(f"{tag}_learned.gif"), b64(f"{tag}_scripted.gif")
        if not l:
            continue
        out.append(f'<figure><figcaption>{title}</figcaption><div class="gg">'
                   f'<div><span>{LABEL}</span><img src="{l}" alt="{title} learned"></div>'
                   f'<div><span>scripted</span><img src="{s}" alt="{title} scripted"></div></div></figure>')
    return "\n".join(out) or "<p class='muted'>(no GIFs rendered)</p>"


# ---- where scripted wins ----
sc_wins = []
for c in cells:
    lf, sf = c["learned"]["fell_fraction"], c["scripted"]["fell_fraction"]
    ls, ss = c["learned"]["forward_speed_mps_mean"], c["scripted"]["forward_speed_mps_mean"]
    if lf - sf > 0.04:
        sc_wins.append(f"<li><b>{c['id']} {c['label']}</b> &mdash; fall rate: scripted {sf:.0%} vs learned {lf:.0%}</li>")
    elif abs(lf - sf) <= 0.04 and ss - ls > 0.004:
        sc_wins.append(f"<li><b>{c['id']} {c['label']}</b> &mdash; speed: scripted {ss:.3f} vs learned {ls:.3f} m/s "
                       f"({(ss-ls)/ss*100:.0f}% faster), same fall rate</li>")
sc_wins_html = "<ul>" + "".join(sc_wins) + "</ul>" if sc_wins else "<p class='muted'>Nothing material.</p>"

html = f"""<title>Decathlon: Learned vs Scripted</title>
<meta name="description" content="Graded easy-to-brutal comparison of G2's learned gait against the scripted wkF walk across every trained skill.">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root{{
    --bg:#f6f4ef; --panel:#fff; --ink:#23262b; --muted:#5c626b; --muted-strong:#8a9099;
    --hair:#e7e4db; --accent:#d9772f;
    --win:#2f7d4f; --win-bg:#e9f3ec; --loss:#b0473d; --loss-bg:#f6e9e7; --tie:#7a7f87; --tie-bg:#efece6;
    --font:"IBM Plex Sans",system-ui,sans-serif; --mono:"IBM Plex Mono",ui-monospace,monospace;
  }}
  @media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
    --bg:#14161a; --panel:#1c1f24; --ink:#e9e7e1; --muted:#a2a8b0; --muted-strong:#7d848d;
    --hair:#2a2e34; --accent:#f0913f;
    --win:#5fbf88; --win-bg:#18291f; --loss:#e0685b; --loss-bg:#2a1c1a; --tie:#9096a0; --tie-bg:#22252b;
  }}}}
  :root[data-theme="dark"]{{
    --bg:#14161a; --panel:#1c1f24; --ink:#e9e7e1; --muted:#a2a8b0; --muted-strong:#7d848d;
    --hair:#2a2e34; --accent:#f0913f;
    --win:#5fbf88; --win-bg:#18291f; --loss:#e0685b; --loss-bg:#2a1c1a; --tie:#9096a0; --tie-bg:#22252b;
  }}
  *{{box-sizing:border-box}}
  body{{background:var(--bg);color:var(--ink);font-family:var(--font);line-height:1.55;margin:0;padding:34px 20px 64px}}
  .wrap{{max-width:940px;margin:0 auto}}
  h1{{font-size:1.6rem;margin:0 0 6px;letter-spacing:-.01em;text-wrap:balance}}
  .head{{font-size:1.05rem;background:var(--panel);border:1px solid var(--hair);border-left:3px solid var(--accent);
        border-radius:10px;padding:16px 18px;margin:18px 0 26px}}
  h2{{font-size:1.1rem;margin:30px 0 12px}}
  .card{{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:18px;margin-bottom:20px;overflow-x:auto}}
  .cap{{font-family:var(--mono);font-size:12px;fill:var(--muted)}}
  .tl{{font-family:var(--mono);font-size:12px;fill:var(--ink)}}
  .v{{font-family:var(--mono);font-size:11px;fill:var(--muted)}}
  table{{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}}
  th,td{{padding:6px 8px;text-align:right;border-bottom:1px solid var(--hair);white-space:nowrap}}
  th{{font-weight:600;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
  td.cid{{text-align:left;font-family:var(--mono);color:var(--muted)}}
  td.lbl{{text-align:left;max-width:230px;white-space:normal}}
  td .s{{display:block;font-family:var(--mono);font-size:10.5px;color:var(--muted-strong)}}
  td.win{{background:var(--win-bg);color:var(--win);font-weight:600}}
  td.loss{{background:var(--loss-bg);color:var(--loss);font-weight:600}}
  td.tie{{background:var(--tie-bg);color:var(--tie)}}
  td.na,td.cs{{color:var(--muted)}}
  .legend{{font-size:12px;color:var(--muted);margin:6px 0 0}}
  .legend b.win{{color:var(--win)}} .legend b.loss{{color:var(--loss)}} .legend b.tie{{color:var(--tie)}}
  ul{{margin:6px 0;padding-left:20px}} li{{margin:5px 0}}
  .muted{{color:var(--muted)}}
  .sk{{display:flex;gap:10px;align-items:baseline;padding:7px 0;border-bottom:1px solid var(--hair)}}
  .sk .n{{font-weight:600;min-width:130px}} .sk .c{{font-size:11px;color:var(--muted);min-width:44px}}
  .sk .win{{color:var(--win)}} .sk .loss{{color:var(--loss)}} .sk .tie{{color:var(--tie)}}
  figure{{margin:0 0 18px}} figcaption{{font-weight:600;margin-bottom:6px;font-size:.95rem}}
  .gg{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
  .gg span{{display:block;font-family:var(--mono);font-size:11px;color:var(--muted);margin-bottom:3px}}
  .gg img{{width:100%;border:1px solid var(--hair);border-radius:8px}}
  .ledger h3{{font-size:.95rem;margin:16px 0 6px;padding-bottom:3px;border-bottom:1px solid var(--hair)}}
  .ledger h3:first-child{{margin-top:0}}
  .ledger h3.win{{color:var(--win)}} .ledger h3.loss{{color:var(--loss)}} .ledger h3.tie{{color:var(--tie)}}
  .ledger li{{margin:6px 0}} .ledger p{{margin-top:14px}}
</style>
<div class="wrap">
  <h1>The Decathlon &mdash; {LABEL} vs the scripted walk</h1>
  <p class="muted">15 cells, 5 tiers, easy &rarr; brutal. Both gaits run every cell on identical courses ({d['episodes']} episodes each). Learned checkpoint: <code>{d['learned_path']}</code>. Scripted = open-loop <code>wkF</code> keyframes (a floor for the real firmware, which adds a gyro-balance layer &mdash; confirm on hardware).</p>

  <div class="head">{head}</div>

  <h2>Where each gait breaks</h2>
  <div class="card">{bars_svg()}
    <p class="legend">Bars are mean fall rate per tier. Shorter is better.</p>
  </div>

  <h2>Skill by skill</h2>
  <div class="card">
    {''.join(f'<div class="sk"><span class="n">{sk}</span><span class="c">{n} cell{"s" if n>1 else ""}</span><span class="{cls}">{v}</span></div>' for sk,n,v,cls in skill_rows())}
  </div>

  <h2>Full scorecard</h2>
  <div class="card">
    <table>
      <thead><tr><th>cell</th><th>course</th>
      {''.join(f'<th>{M[m][0]}</th>' for m in M)}<th>cond. surv</th></tr></thead>
      <tbody>
      {scorecard()}
      </tbody>
    </table>
    <p class="legend">Each cell shows the <b>learned</b> value, with the <b>scripted</b> value small underneath.
      <b class="win">green</b> = learned better &nbsp; <b class="loss">red</b> = scripted better &nbsp; <b class="tie">grey</b> = tie.
      cond. surv = of the courses where scripted fell, the share the learned gait stayed up on (denominator = scripted falls).</p>
  </div>

  <h2>Watch it</h2>
  <div class="card">{gif_block()}</div>

  <h2>Progress ledger &mdash; what G2 has actually learned</h2>
  <div class="card ledger">
    <h3 class="win">Genuinely gained &mdash; kept, and in this gait</h3>
    <ul>
      <li><b>A closed-loop walk.</b> The policy is a per-step correction on top of the scripted <code>wkF</code> keyframes, driven by the IMU. The scripted gait is open-loop and cannot react; this one does, every control step.</li>
      <li><b>Slopes.</b> Trained on &plusmn;10&deg; random ground tilt. Walks uphill, downhill and cross-slope to ~14&deg; without falling &mdash; the one clearly-kept scenario gain of the whole coverage loop.</li>
      <li><b>Slope training transferred.</b> Fewer falls on the obstacle and shove cells than the pre-slope gait (obst-35 7&rarr;0%, push-hard 64&rarr;50%, obst+push 46&rarr;36%).</li>
      <li><b>Reactive stumble-catch.</b> A dense "fight back to level" reward produces active saves from big wobbles &mdash; it recovers from ~20&ndash;30% of the shoves that drop the scripted gait, which recovers from <b>none</b> (it cycles keyframes until it is face down).</li>
      <li><b>Obstacle traversal.</b> Trained with randomised obstacle heights; handles 20&ndash;50&nbsp;mm.</li>
      <li><b>Straight-line hold</b> &mdash; at its training cadence, a near-perfect line (0.004&nbsp;m lateral drift over a full episode).</li>
      <li><b>Adaptive push curriculum</b> (training-side): per-environment disturbance intensity scales with recent survival rate &mdash; the one research lever from the survive-loop that helped.</li>
    </ul>
    <h3 class="loss">Tried and reverted &mdash; no net gain</h3>
    <ul>
      <li><b>S1&ndash;S14 survive-loop</b> &mdash; 14 rounds of reward shaping for reactive recovery, all plateaued &le;25% conditional survival.</li>
      <li><b>Coverage loop R2&ndash;R4 + R-rob</b> &mdash; slip patch, start-pose jitter, sustained shove, heavier disturbances + a fall penalty. All reverted, no capability gained.</li>
      <li><b>Drift-fix D1&ndash;D2</b> &mdash; mirror-symmetry reward and cadence randomisation. Both reverted; the off-cadence drift was not fixed.</li>
      <li><b>MIN_SPEED bump, field-standard reward recipe</b> &mdash; reverted, underperformed.</li>
    </ul>
    <h3 class="tie">Known ceilings</h3>
    <ul>
      <li><b>~25% reactive-recovery ceiling</b> &mdash; a platform limit (IMU-only sensing, no roll-axis joint, weak ~0.29&nbsp;N&middot;m servos), not a tuning problem. Held across ~20 rounds.</li>
      <li><b>No self-right from supine</b> &mdash; no roll-axis actuator to push with. Firmware's scripted self-right covers side/forward falls only.</li>
      <li><b>Straight-line only</b> &mdash; the learned gait cannot turn on command; turning is delegated to firmware.</li>
      <li><b>Off-cadence drift</b> &mdash; holds a line only at its exact training cadence; run it slower/faster and it drifts ~0.04&ndash;0.12&nbsp;m/episode. Six fix attempts failed &mdash; it needs commanded-locomotion training, not a reward tweak.</li>
      <li><b>~10% slower than scripted on flat</b> (0.09 vs 0.10&nbsp;m/s) &mdash; the cost of the correction layer + slope robustness.</li>
    </ul>
    <h3>Beyond the gait</h3>
    <ul>
      <li>Full Pi Zero 2 W bring-up prep &mdash; provisioning script, voice-pipeline benchmark harness, model fetcher, pinned + verified ARM dependencies, a researched runbook. Ready the moment the SD adapter arrives.</li>
      <li>Recovery state machine + <code>krc</code>/<code>krl</code> serial tokens in <code>pi_pipeline</code> (42 passing tests).</li>
      <li>Bittle-RL landscape survey &mdash; identified the real headroom (symmetry rewards, wider residual, actuator-delay DR, commanded locomotion); confirmed nobody has a robust closed-loop RL gait on real Bittle hardware.</li>
      <li>A staged refinement regimen to get the gait to where a 20M-step run is justified.</li>
    </ul>
    <p><b>Bottom line:</b> the gait is meaningfully more capable than a raw scripted walk on <i>terrain</i>, and it can <i>recover</i> where scripted cannot &mdash; but it is slightly slower on flat, cannot turn, drifts off-cadence, and has a hard reactive-recovery ceiling. The next real gains need the refinement regimen (wider residual, completed reward, expanded domain randomisation, commanded locomotion), not more one-off scenario rounds.</p>
  </div>

  <h2>Where the scripted gait still wins</h2>
  <div class="card">{sc_wins_html}</div>

  <h2>Bottom line for the hardware head-to-head</h2>
  <div class="card">
    <p>Averaged over the ladder: learned falls <b>{fell_l:.0%}</b> vs scripted <b>{fell_s:.0%}</b>;
       learned walks <b>{spd_l:.3f} m/s</b> vs scripted <b>{spd_s:.3f} m/s</b>.
       {'The learned gait recovered from ' + f'{pooled_cs:.0%}' + ' of the courses where the scripted gait fell.' if pooled_cs is not None else ''}</p>
    <p class="muted">Caveats for the real robot: the scripted baseline here is open-loop (the firmware's <code>wkF</code>
       adds a tuned gyro-balance layer, so real scripted performance &ge; this); and the sim runs the policy at 80&nbsp;Hz
       while the BiBoard runs ~50&nbsp;Hz &mdash; expect some heading drift on hardware from that cadence gap alone.</p>
  </div>
</div>
"""
Path(OUT).write_text(html)
print(f"wrote {OUT}  ({wins} learned-better / {losses} scripted-better / {ties} tie metric-cells)")
