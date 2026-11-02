"""Status of the sim training run: python tools/sim_train/status.py [RUN_DIR]   (default: the newest run, ~/g2_sim_train/CURRENT_RUN)"""
import json, os, re, sys, time
run = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else open(os.path.expanduser("~/g2_sim_train/CURRENT_RUN")).read().strip())
st = json.load(open(os.path.join(run, "state.json"))) if os.path.exists(os.path.join(run, "state.json")) else {}
lines = open(os.path.join(run, "progress.log")).read().splitlines() if os.path.exists(os.path.join(run, "progress.log")) else []
print(f"run: {run}\nstage: {st.get('stage', '?')}{'   (DONE)' if os.path.exists(os.path.join(run, 'DONE')) else ''}")
gen_lines = [l for l in lines if " combo " in l and " gen " in l]
if gen_lines:
    m = re.search(r"combo (\d+)/(\d+) (\S+) gen (\d+)/(\d+)", gen_lines[-1]); ci, nc, key, g, G = m.group(1), m.group(2), m.group(3), int(m.group(4)), int(m.group(5))
    done = sum(c["gen"] for c in st.get("combos", {}).values()); total = int(nc) * G
    t0 = time.mktime(time.strptime(time.strftime("%Y-%m-%d ") + gen_lines[0][:8], "%Y-%m-%d %H:%M:%S")); t1 = time.mktime(time.strptime(time.strftime("%Y-%m-%d ") + gen_lines[-1][:8], "%Y-%m-%d %H:%M:%S"))
    if t1 < t0: t1 += 86400
    rate = (t1 - t0) / max(1, done - 1); eta = rate * (total - done) + 12 * 60       # + the final re-scoring (about 12 min)
    print(f"search: combo {ci}/{nc} ({key}) generation {g}/{G};  {done}/{total} generations done ({100 * done // total}%)")
    print(f"pace: {rate:.1f} s per generation; estimated finish about {time.strftime('%I:%M %p', time.localtime(time.time() + eta)).lstrip('0')} (search + about 12 min of final scoring)")
    best = sorted(((c["best"]["J"], k) for k, c in st.get("combos", {}).items() if c.get("best")), reverse=True)[:5]
    print("best so far (objective J, higher is better; the current real settings score about 0.2 here):"); [print(f"   {j:.3f}  {k}") for j, k in best]
elif lines: print(lines[-1][:200])
if "validation" in st: v = st["validation"]; print(f"simulator vs real: hit rate {v['sim_hit_rate']} vs {v['real']['hit_rate']} real; mean score {v['sim_mean_score']} vs {v['real']['mean_score']}")
print("last:", lines[-1][:150] if lines else "-")
if os.path.exists(os.path.join(run, "report.html")): print("REPORT:", os.path.join(run, "report.html"))
