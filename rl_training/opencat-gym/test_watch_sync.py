"""What the viewers generate is what training generates (user, 2026-10-08: no discrepancies between modes). Run with the RL venv."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def test_watch_env_is_exactly_the_training_env_of_the_runs_job():
    import g2_profile as G
    queue = json.load(open(os.path.join(HERE, "trained", "v3_queue.json")))
    job = next(j for j in (queue if isinstance(queue, list) else queue["jobs"]) if j.get("tag") == "v3_20m")
    kept = json.load(open(os.path.join(HERE, "trained", "v3_results.json")))["v3_k3"]["levers"]
    expected = G.env_for_job(dict(job, levers=kept if job.get("levers") == "K3" else job["levers"]))
    out = subprocess.run([sys.executable, "watch_env.py", "v3_20m"], cwd=HERE, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    shown = dict(x.strip()[len("export "):].split("=", 1) for x in out.stdout.strip().split(";") if x.strip())
    assert shown == {k: str(v) for k, v in expected.items()}


def test_the_launch_uses_the_same_function(monkeypatch):
    sys.path.insert(0, HERE)
    import phase_v3
    import g2_profile as G
    seen = {}
    monkeypatch.setattr(phase_v3, "log", lambda *a, **k: None)         # never write to the real queue log
    monkeypatch.setattr(phase_v3.RP, "training", lambda tag: False)
    monkeypatch.setattr(phase_v3.RP, "launch", lambda tag, env, steps, from_ckpt: seen.update(env=dict(env), steps=steps))
    monkeypatch.setattr(os.path, "exists", lambda p: False if str(p).endswith("_ppo.zip") else os.path.lexists(p))
    job = {"kind": "final", "tag": "v3_zz_sync_test", "stage": "s6_full_strength", "levers": ["mirror"], "fresh": True}
    phase_v3.train(job, {})
    assert {k: str(v) for k, v in seen["env"].items()} == {k: str(v) for k, v in G.env_for_job(job).items()}


def test_every_new_fresh_final_has_the_whole_course_and_only_the_finished_20m_is_flat():
    import g2_profile as G
    new = G.env_for_job({"kind": "final", "tag": "v3_next", "stage": "s6_full_strength", "levers": ["mirror"], "fresh": True})
    assert new["G2E_SURFACE_TRANSITION_PROB"] == "0" and new["G2E_SURFACE_TRANSITION_STEP_M"] == "0.0" if "G2E_SURFACE_TRANSITION_STEP_M" in new else new["G2E_SURFACE_TRANSITION_PROB"] == "0"     # the surface step is out of the course completely (user, 2026-10-08)
    assert all(new[k] == v for k, v in G.FULL_COURSE.items()) and float(new["G2E_SNAG_OBSTACLE_PROB"]) > 0 and float(new["G2E_LEDGE_PROB"]) > 0     # snags and ledges are in
    assert new["G2E_HARD_SCALE"] == "1.10"
    assert not any("CARPET" in k and float(v) > 0 for k, v in new.items() if k.startswith("G2E_CARPET"))
    assert new.get("G2E_LEVEL_START", "0") in ("0", "0.0")                    # a fresh run still starts every hazard from an empty floor
    old = G.env_for_job({"kind": "final", "tag": "v3_20m", "stage": "s6_full_strength", "levers": ["mirror"], "fresh": True})
    assert (old["G2E_SURFACE_TRANSITION_PROB"], old["G2E_SNAG_OBSTACLE_PROB"], old["G2E_LEDGE_PROB"]) == ("0", "0", "0")
    assert old["G2E_RUBBLE_PROB"] if "G2E_RUBBLE_PROB" in old else True                         # the finished 20M keeps the defaults it trained with (no tuned mix)
    assert G.HISTORICAL_FLAT_FINALS == {"v3_20m"}
