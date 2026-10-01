"""Replay real walk logs' joint commands open-loop in the sim and print real vs sim roll/pitch
swing, forward distance and heading (run from rl_training/opencat-gym with the RL venv).

    ../../.venv/bin/python sim_vs_real_walk.py [log ...]      # default: ~/g2_runs/hard_v21_run0[1-6].csv

Caveat: the logged commands came out of a closed-loop policy reacting to the REAL IMU, so an
open-loop replay can diverge (the sim robot may simply fall over); trust the replays that stay
upright. Uses sysid_replay.build_sim (spine + head payload with real box inertia).
"""
import sys, os, numpy as np, pybullet as p
sys.path.insert(0, os.getcwd())
import sysid_replay as S

def replay_pos(t, jd_deg, jids, rid, mf, kp, kd, lat):
    jr = np.deg2rad(jd_deg)
    p.resetBasePositionAndOrientation(rid, [0, 0, 0.08], [0, 0, 0, 1]); p.resetBaseVelocity(rid, [0,0,0],[0,0,0])
    for k, j in enumerate(jids): p.resetJointState(rid, j, float(jr[0][k]))
    for _ in range(120):
        p.setJointMotorControlArray(rid, jids, p.POSITION_CONTROL, jr[0], forces=[mf]*8, positionGains=[kp]*8, velocityGains=[kd]*8); p.stepSimulation()
    buf=[jr[0]]*max(1,lat+1); rp=np.empty((len(t),2)); prev=t[0]
    pos0=np.array(p.getBasePositionAndOrientation(rid)[0]); yaw0=p.getEulerFromQuaternion(p.getBasePositionAndOrientation(rid)[1])[2]
    for i in range(len(t)):
        buf.append(jr[i]); tgt=buf.pop(0)
        nsub=1 if i==0 else max(1,int(round((t[i]-prev)*S.SUBSTEP_HZ))); prev=t[i]
        for _ in range(min(nsub,24)):
            p.setJointMotorControlArray(rid, jids, p.POSITION_CONTROL, tgt, forces=[mf]*8, positionGains=[kp]*8, velocityGains=[kd]*8); p.stepSimulation()
        pos,q=p.getBasePositionAndOrientation(rid); e=p.getEulerFromQuaternion(q); rp[i]=(e[0],e[1])
    pos,q=p.getBasePositionAndOrientation(rid)
    return rp, np.array(pos)-pos0, np.degrees(p.getEulerFromQuaternion(q)[2]-yaw0)

_cid, rid, jids, plane = S.build_sim(surface="hard")
print("run                 | real roll std/range   | sim roll std/range    | real pitch std | sim pitch std | sim fwd dist m, yaw deg | real yaw")
logs = sys.argv[1:] or [os.path.expanduser(f"~/g2_runs/hard_v21_run0{i}.csv") for i in range(1, 7)]
for path in logs:
    n = os.path.basename(path)[:-4]
    t, rrp, rg, jd, _ = S.load_log(path)
    srp, dpos, dyaw = replay_pos(t, jd, jids, rid, 0.20, 0.1, 1.0, 0)
    d=np.degrees
    # remove each series' own mean so we compare swing, not the IMU zero
    rr, sr = d(rrp[:,0]), d(srp[:,0]); rp_, sp = d(rrp[:,1]), d(srp[:,1])
    yaw_real = None
    import csv
    yaws=[float(r[3]) for r in csv.reader(l for l in open(path) if not l.startswith('#') and not l.startswith('t,'))]
    yaw_real = np.degrees(yaws[-1]-yaws[0])
    print(f"{n} | {rr.std():4.1f} [{rr.min():+.0f},{rr.max():+.0f}] | {sr.std():4.1f} [{sr.min():+.0f},{sr.max():+.0f}] | {rp_.std():4.1f} | {sp.std():4.1f} | {np.hypot(dpos[0],dpos[1]):.2f} m, {dyaw:+.0f} | {yaw_real:+.0f}")
