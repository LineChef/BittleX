"""Apply the sim training's recommended starting values to G2 (owner's decision 2026-11-02: apply automatically, with a backup, reversible):
    python tools/sim_train/apply.py RUN_DIR          # back up, then write the values into the Pi's punt_settings.json and reset what the goal LEARNED for just the settings that change
    python tools/sim_train/apply.py --revert BACKUP_DIR
Why both: at the start of a session the goal takes the best-supported value from its real records and only falls back to the settings file where it has none, so the file alone would change
nothing for arm on hardwood. `goals forget` (scope arm on hardwood) drops the records of a setting that changes; settings whose value is unchanged keep their real evidence. The pinned
settings are never touched. Exit codes: 0 applied or nothing to apply, 2 the Pi is not reachable or is busy (try again later), 1 an error. Needs G2_PI (<user>@g2pi.local, from your shell profile)."""
import json, os, subprocess, sys, time
PI = os.environ.get("G2_PI") or sys.exit("set G2_PI=<user>@g2pi.local (kept in your shell profile, not in the repo)")
G = "~/.local/share/g2"; SCOPE = "attachment=arm|floor=hardwood"
PY = "cd ~/bittleX && PYTHONPATH=. pi_pipeline/.venv/bin/python"
FILES = ("punt_settings.json", "goal_state.json", "goal_overrides.json")


def ssh(cmd, timeout=60):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", PI, cmd], capture_output=True, text=True, timeout=timeout)


def same(a, b):
    """The learned value equals the recommended one (numbers compared as numbers; a missing value is not the same)."""
    if a is None: return False
    try: return float(a) == float(b)
    except (TypeError, ValueError): return a == b


def busy():
    r = ssh("pgrep -af 'explore_session|goals run|ball_chase|run_gait|claw_look|punt_test' | grep -v pgrep | head -1")
    return r.returncode == 255, r.stdout.strip()


def revert(d):
    d = os.path.expanduser(d); stamp = os.path.basename(d.rstrip("/"))
    down, run = busy()
    if down or run: print("Pi unreachable or busy:", run or "no answer"); return 2
    ssh(f"mkdir -p /tmp/{stamp}")
    for f in FILES:
        p = os.path.join(d, f)
        if os.path.exists(p): subprocess.run(["scp", "-q", p, f"{PI}:/tmp/{stamp}/{f}"], check=True); ssh(f"cp /tmp/{stamp}/{f} {G}/{f}")
    print("reverted: punt_settings.json, goal_state.json and goal_overrides.json restored from", d); return 0


def main():
    if sys.argv[1] == "--revert": return revert(sys.argv[2])
    run = os.path.expanduser(sys.argv[1]); rec = json.load(open(os.path.join(run, "recommended_punt_settings.json")))
    if str(rec.get("winner", "")).startswith("none"): print("nothing to apply:", rec["winner"]); return 0
    down, running = busy()
    if down or running: print("Pi unreachable or busy:", running or "no answer"); return 2
    stamp = time.strftime("sim_%Y%m%d_%H%M%S"); back = os.path.expanduser(f"~/g2_sim_train/backups/{stamp}"); os.makedirs(back, exist_ok=True)
    ssh(f"mkdir -p {G}/backups/{stamp}; for f in {' '.join(FILES)}; do cp {G}/$f {G}/backups/{stamp}/ 2>/dev/null; done")
    for f in FILES: subprocess.run(["scp", "-q", f"{PI}:{G}/backups/{stamp}/{f}", back + "/"], capture_output=True)
    if not os.path.exists(back + "/goal_state.json"): print("backup of the goal state failed: stopping"); return 1
    state = json.load(open(back + "/goal_state.json")); cur = ((state.get("ball_punt") or {}).get(SCOPE) or {}).get("current", {})
    changed = []
    for name, val in rec["recommended_settings"].items():
        r = ssh(f"{PY} -m pi_pipeline.behavior.punt_settings --set {name} {val}")
        if r.returncode: print("could not set", name, r.stdout, r.stderr); return 1
        if not same(cur.get(name), val):
            changed.append(name)
    for name in changed:
        r = ssh(f"{PY} -m pi_pipeline.goals forget ball_punt {name} --scope '{SCOPE}'"); print(r.stdout.strip() or r.stderr.strip())
    print(f"APPLIED {len(rec['recommended_settings'])} starting values ({len(changed)} changed from what G2 had learned: {', '.join(changed) or 'none'}).")
    print(f"Backup: {back}\nRevert:  python tools/sim_train/apply.py --revert {back}")
    json.dump({"applied": time.strftime("%Y-%m-%d %H:%M:%S"), "run": run, "changed": changed, "backup": back}, open(os.path.join(run, "APPLIED"), "w")); return 0


if __name__ == "__main__":
    sys.exit(main())
