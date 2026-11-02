"""Closed-loop simulation of the ball chase (2026-11-02): the REAL ball_chase.run_chase runs against a simulated world (a ball, a camera that draws it the way the finder reads it, a robot
with G2's measured pace 4.2 in/s and turn rate 6 deg/s plus noise). Nothing here touches hardware. Use it to check a change to the chase logic before a hardware session:

    python tools/sim_chase.py [REPO_ROOT] [N] [stand|attention]       # N random starts (ball ahead / angled / to the side / behind / far); prints the hit rate per kind and the still time before moves
    REPO_ROOT can be another checkout (git worktree add /tmp/old <commit>): the same seeds give the same starts, so two versions can be compared run for run.

Known limits: no walls, no falls, no sag, no serial traffic; the search is the default plain turns, so a ball behind him is not found inside 75 s. It tests decisions, not hardware."""
import math, os, random, sys, statistics as st
root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200; flow = sys.argv[3] if len(sys.argv) > 3 else "stand"
sys.path.insert(0, root); sys.path.insert(0, root + "/pi_pipeline/tests")
import numpy as np
from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.tests.test_ball_chase import picture, disc
if hasattr(bc, "BETWEEN_MOVES"): bc.BETWEEN_MOVES = flow
bc.CLAW_PAN_SIGN = "left"

class World:
    def __init__(self, rng, bx, by, hdg):
        self.rng, self.t = rng, 0.0
        self.x = self.y = 0.0; self.h = hdg            # robot: inches, heading deg (0 = +x), + = counter-clockwise (left)
        self.bx, self.by, self.punted = bx, by, False
        self.pan = 0.0; self.still = []; self.moved_at = 0.0; self.sag_s = None
    def rel(self):                                       # ball in the camera frame: forward f, lateral l (+ right)
        cam = self.h + (self.pan if bc.CLAW_PAN_SIGN == "left" else -self.pan)      # positive pan turns the camera LEFT
        dx, dy = self.bx - self.x, self.by - self.y
        a = math.radians(cam)
        f = dx * math.cos(a) + dy * math.sin(a); l = dx * math.sin(a) - dy * math.cos(a)
        return f, l
    def move_begin(self):
        self.still.append(round(self.t - self.moved_at, 1))
    def move_end(self): self.moved_at = self.t

class Cam:
    def __init__(self, w): self.w = w
    def look(self):
        w = self.w; w.t += 1.5                                           # the camera answers about 1.5 s after a request
        f, l = w.rel()
        if f < 1.8 or f > 60: return picture()
        diam = 330.0 / f * w.rng.uniform(0.95, 1.05)
        cx = 120 + l * diam / 3.0 + w.rng.gauss(0, 1.0)
        if not (0 <= cx < 240) or diam > 200: return picture()
        return picture([disc(cx, 150, diam / 2)])
    def refresh_exposure(self): pass

class Bot:
    use_pick = False; bumped = False
    def __init__(self, w): self.w = w
    def _go(self, secs): self.w.move_begin(); self.w.t += secs
    def walk(self, secs):
        w = self.w; self._go(secs); d = 4.2 * secs * w.rng.uniform(0.75, 1.1)
        f, l = w.rel(); a = math.radians(w.h)
        step = min(d, max(0.0, f - 2.6)) if abs(l) < 2.5 and f > 0 else d          # he stops against the ball
        w.h += w.rng.gauss(0, 1.5)
        w.x += step * math.cos(math.radians(w.h)); w.y += step * math.sin(math.radians(w.h))
        w.move_end(); return "ok"
    def turn(self, deg, secs):
        w = self.w; self._go(secs); got = 6.0 * secs * w.rng.uniform(0.7, 1.15) * (1 if deg > 0 else -1)
        w.h -= got                                                       # + = right = clockwise
        w.move_end(); return "ok"
    def back(self, secs):
        w = self.w; self._go(secs); d = 2.5 * secs
        w.x -= d * math.cos(math.radians(w.h)); w.y -= d * math.sin(math.radians(w.h)); w.move_end(); return "ok"
    def three_point_turn(self, deg, back_s, fwd_s): self.back(back_s); return self.turn(deg, abs(deg) / 6.0)
    def punt(self):
        w = self.w; self._go(1.5); f, l = w.rel()
        if f <= 4.2 and abs(l) <= 1.6:
            w.punted = True; w.bx += 18 * math.cos(math.radians(w.h)); w.by += 18 * math.sin(math.radians(w.h))
        w.move_end(); return "ok"
    def battery_ok(self): return True
    def claw_pose(self, pan, lift): self.w.t += abs(pan - self.w.pan) / 60.0 + 0.2; self.w.pan = pan; return "ok"
    def sit_down(self): self.w.move_begin(); self.w.t += 4.5; return "ok"
    def stand_from_sit(self): self.w.t += 2.5; self.w.move_end(); return "ok"
    def relax(self): return "ok"

res = []
for i in range(N):
    rng = random.Random(1000 + i)
    kind = rng.choice(["ahead", "ahead", "angled", "angled", "side", "behind", "far"])
    dist = {"ahead": rng.uniform(14, 30), "angled": rng.uniform(12, 30), "side": rng.uniform(12, 24), "behind": rng.uniform(10, 22), "far": rng.uniform(36, 55)}[kind]
    ang = {"ahead": rng.uniform(-8, 8), "angled": rng.choice([-1, 1]) * rng.uniform(15, 45), "side": rng.choice([-1, 1]) * rng.uniform(55, 100), "behind": rng.uniform(120, 240), "far": rng.uniform(-15, 15)}[kind]
    w = World(rng, dist * math.cos(math.radians(ang)), dist * math.sin(math.radians(ang)), 0.0)
    bot, cam = Bot(w), Cam(w)
    bc.ChasePlanner  # real planner
    trace = []
    try:
        ended = bc.run_chase(bot, cam, lambda: False, max_punts=1, max_seconds=75.0, clock=lambda: w.t, sleep=lambda s: setattr(w, "t", w.t + s), say=lambda m: None, trace=trace)
    except Exception as e:
        ended = "EXC:" + repr(e)[:80]
    res.append((kind, ended, round(w.t, 1), w.punted, w.still))
ok = [r for r in res if r[3]]
print(f"flow={flow}  runs={N}  punted a real hit: {len(ok)} ({100*len(ok)//N}%)  ended: " + str({k: sum(1 for r in res if r[1] == k) for k in sorted({r[1] for r in res})}))
for kind in ("ahead", "angled", "side", "behind", "far"):
    rs = [r for r in res if r[0] == kind]
    print(f"  {kind:7s} n={len(rs):3d}  hit {100*sum(r[3] for r in rs)//max(1,len(rs)):3d}%  median time {st.median([r[2] for r in rs]):5.1f} s")
stills = [s for r in res for s in r[4][1:]]
first = [r[4][0] for r in res if r[4]]
print(f"  still before a move (sim): median {st.median(stills):.1f} s, 90th pct {sorted(stills)[int(len(stills)*.9)]:.1f} s, over 5 s: {100*sum(s>5 for s in stills)//len(stills)}%, over 7 s: {100*sum(s>7 for s in stills)//len(stills)}%; first move of an attempt median {st.median(first):.1f} s")
