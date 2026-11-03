"""The simulated world for the sim training (2026-11-02): the REAL ball_chase.run_chase and the goal's own scorer run against a fast 2D model of G2, the ball and a room.
Physics come from calibration.json (tools/sim_train/calibrate.py), randomized per attempt inside the measured spread. No images are drawn: find_ball is patched to read the reading
the simulated camera made. Known limits: walls are bumps (no wall reading), the punch is a fitted hit chance (13 real punts), turn data is thin (wide spread)."""
import json, math, os, random, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.behavior import punt_settings as ps
from pi_pipeline.vision.ball_finder import BallReading
from pi_pipeline.goals.approach import AttemptResult

CAL_PATH = os.path.expanduser("~/g2_sim_train/calibration.json")
TRAIN_FAMILIES = ("ahead", "angled", "side", "behind", "far", "wall_ball")
HOLDOUT_FAMILIES = ("corner", "dim", "decoy")
PINNED = {"punt_align_deg": 12.0, "align_pulse_min_s": 1.0, "align_tries": 3, "when_misaligned": "punch", "claw_look_pan_deg": 35.0, "claw_look_lift_deg": 15.0,
          "claw_pan_sign": "left", "max_seconds": 75.0}
import contextlib


@contextlib.contextmanager
def patched():
    """The simulation's changes to ball_chase (the finder reads the simulated camera's reading; the searched settings; the standing flow), for the length of one attempt only and put back
    after: a test (or anything else in the process) that imports this module must see the real chase code (2026-11-02: patching at import broke 28 other tests)."""
    names = [c for c, *_ in ps.SPEC.values() if c] + ["find_ball", "BETWEEN_MOVES"]
    saved = {n: getattr(bc, n) for n in names if hasattr(bc, n)}
    bc.find_ball = lambda pic: pic[1]                     # the simulated camera hands the reading itself
    bc.BETWEEN_MOVES = "stand"
    logs = ("G2_TURN_LOG", "G2_DECISION_LOG")                  # the chase writes a line per turn and per decision: a simulated attempt must never write to the real logs (2026-11-02: a training run put 42 GB in the turn log)
    old_env = {k: os.environ.get(k) for k in logs}
    for k in logs: os.environ[k] = os.devnull
    try:
        yield
    finally:
        for n, v in saved.items(): setattr(bc, n, v)
        for k, v in old_env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def load_cal():
    try: return json.load(open(CAL_PATH))
    except OSError: return {}


class StubPace:                                          # what G2's pace book says on hardwood (chase_pace.json): the planner times moves from it
    def walk_in_s(self): return 2.09
    def turn_deg_s(self, side, short): return 24.5 if (short and side > 0) else (4.0 if short else 6.0)
    def record_walk(self, *a): return None
    def record_turn(self, *a): return None
    def snapshot(self): return {}


class World:
    def __init__(self, rng, family, cal):
        self.rng, self.family, self.t = rng, family, 0.0
        w = cal.get("walk", {})
        self.v = max(1.2, rng.gauss(w.get("in_per_s") or 2.5, 0.35)); self.dead = max(0.0, rng.gauss(w.get("dead_s") or 0.6, 0.2))
        self.walk_sd_in = 2.0; self.drift_sd = 6.0
        self.turn_gain_long = rng.lognormvariate(math.log(0.75), 0.35); self.pulse_sd = 0.4
        self.cam_s = rng.lognormvariate(math.log(0.7), 0.4); self.overhead_s = max(0.5, rng.gauss(2.0, 0.4))
        self.drop = 0.08; self.miss = 0.35 if family == "dim" else 0.05; self.decoy = 0.12 if family == "decoy" else 0.01
        self.p_hit = min(0.7, max(0.2, rng.gauss(0.40, 0.08)))
        W, H = rng.uniform(60, 140), rng.uniform(60, 140)
        self.W, self.H = W, H
        self.x, self.y, self.h = rng.uniform(15, W - 15), rng.uniform(15, H - 15), rng.uniform(0, 360)
        self._place_ball(); self.pan = 0.0; self.punted = False; self.bumped = False; self.moved_at = 0.0; self.rolled = False

    def _place_ball(self):
        r, f = self.rng, self.family
        if f == "wall_head_on":                               # the ball lies 3-9 in from a wall and he is walking at it: the case the sidestep is for
            side = r.choice("WESN"); near = r.uniform(3, 9); gap = r.uniform(14, 34)
            ang = {"W": 180.0, "E": 0.0, "S": 270.0, "N": 90.0}[side]
            if side in "WE": bx = near if side == "W" else self.W - near; by = r.uniform(25, self.H - 25); self.x = bx - math.cos(math.radians(ang)) * (near + gap) * -1 if False else (bx + gap if side == "W" else bx - gap); self.y = by + r.uniform(-4, 4)
            else: by = near if side == "S" else self.H - near; bx = r.uniform(25, self.W - 25); self.y = (by + gap if side == "S" else by - gap); self.x = bx + r.uniform(-4, 4)
            self.h = ang + r.gauss(0, 5); self.bx, self.by = bx, by; self.W = max(self.W, 90.0); self.H = max(self.H, 90.0); return
        for _ in range(200):
            if f == "ahead": d, a = r.uniform(14, 30), r.uniform(-8, 8)
            elif f == "angled": d, a = r.uniform(12, 32), r.choice([-1, 1]) * r.uniform(15, 55)
            elif f == "side": d, a = r.uniform(10, 28), r.choice([-1, 1]) * r.uniform(60, 110)
            elif f == "behind": d, a = r.uniform(10, 30), r.uniform(120, 240)
            elif f == "lost": d, a = r.uniform(12, 28), r.choice([-1, 1]) * r.uniform(45, 65)         # at the edge of the picture: a little drift or a turn and it is gone
            elif f == "far": d, a = r.uniform(34, 60), r.uniform(-20, 20)
            else: d, a = r.uniform(10, 40), r.uniform(-180, 180)
            bx, by = self.x + d * math.cos(math.radians(self.h - a)), self.y + d * math.sin(math.radians(self.h - a))
            near = r.uniform(3, 9)
            if f == "wall_ball":                              # the ball is against a wall
                side = r.choice("WESN")
                if side == "W": bx = near
                elif side == "E": bx = self.W - near
                elif side == "S": by = near
                else: by = self.H - near
            if f == "corner": bx, by = r.choice([near, self.W - near]), r.choice([r.uniform(3, 9), self.H - r.uniform(3, 9)])
            if 3 < bx < self.W - 3 and 3 < by < self.H - 3 and math.hypot(bx - self.x, by - self.y) > 8: self.bx, self.by = bx, by; return
        self.bx, self.by = self.W / 2, self.H / 2

    def _ray(self, x, y, ang_deg, lo=0.0):
        """Distance from (x, y) along `ang_deg` to the room's boundary (inset by `lo`)."""
        dx, dy = math.cos(math.radians(ang_deg)), math.sin(math.radians(ang_deg)); ts = []
        if dx > 1e-9: ts.append((self.W - lo - x) / dx)
        elif dx < -1e-9: ts.append((lo - x) / dx)
        if dy > 1e-9: ts.append((self.H - lo - y) / dy)
        elif dy < -1e-9: ts.append((lo - y) / dy)
        return max(0.0, min(ts)) if ts else 1e9

    def slide(self, x, y, ang_deg, d, lo=3.0):
        """The ball rolls `d` inches along `ang_deg`; it bounces off the walls (keeps 60% of its way at each) so a punch straight into a wall comes straight back and one at an angle banks away."""
        dx, dy = math.cos(math.radians(ang_deg)), math.sin(math.radians(ang_deg))
        for _ in range(4):
            t = self._ray(x, y, math.degrees(math.atan2(dy, dx)), lo)
            if d <= t: return x + d * dx, y + d * dy
            x, y = x + t * dx, y + t * dy; d = (d - t) * 0.6
            if x <= lo + 1e-6 or x >= self.W - lo - 1e-6: dx = -dx
            if y <= lo + 1e-6 or y >= self.H - lo - 1e-6: dy = -dy
            if abs(dx) < 1e-9 and abs(dy) < 1e-9: break
        return x, y

    def wall_reading(self, ball):
        """What the wall estimator would say: the nearest wall ahead, the side with more room, and (with the ball in view) how far the wall is behind the ball. Capped at 50 in, a little noise."""
        cam = self.h + (self.pan if bc.CLAW_PAN_SIGN == "left" else -self.pan)
        n = min(50.0, self._ray(self.x, self.y, cam) + self.rng.gauss(0, 0.8))
        turn = "left" if self._ray(self.x, self.y, cam + 40) > self._ray(self.x, self.y, cam - 40) else "right"
        behind = None
        if ball is not None:
            ang = cam - ball.bearing_deg
            behind = min(50.0, self._ray(self.x, self.y, ang) * math.cos(math.radians(ball.bearing_deg)) + self.rng.gauss(0, 0.8))
        return bc.WallSeen(round(n, 1), turn, None if behind is None else round(behind, 1))

    def rel(self):                                           # the ball in the camera frame: forward f, lateral l (+ right)
        cam = self.h + (self.pan if bc.CLAW_PAN_SIGN == "left" else -self.pan)
        dx, dy = self.bx - self.x, self.by - self.y; a = math.radians(cam)
        return dx * math.cos(a) + dy * math.sin(a), dx * math.sin(a) - dy * math.cos(a)

    def advance(self, d):                                   # forward d inches (negative = back); bumps stop at the room's walls
        nx, ny = self.x + d * math.cos(math.radians(self.h)), self.y + d * math.sin(math.radians(self.h))
        bx, by = max(4.5, min(self.W - 4.5, nx)), max(4.5, min(self.H - 4.5, ny))
        if (bx, by) != (nx, ny): self.bumped = d > 0
        f, l = self.rel()
        if d > 0 and abs(l) < 2.8 and 0 < f:                # the claw reaches the ball: he stops against it
            d = max(0.0, min(d, f - 2.6)); bx, by = self.x + d * math.cos(math.radians(self.h)), self.y + d * math.sin(math.radians(self.h))
        self.x, self.y = bx, by


class Camera:
    def __init__(self, w): self.w = w
    def refresh_exposure(self): pass
    def look(self):
        w = self.w; w.t += w.cam_s
        if w.rng.random() < w.drop: return None             # no picture
        f, l = w.rel(); rd = None
        if 1.8 <= f <= 60 and w.rng.random() > w.miss:
            diam = 330.0 / f * w.rng.uniform(0.94, 1.06); cx = 120 + l * diam / 3.0
            if 0 <= cx < 240 and diam < 200:
                fd = f * w.rng.uniform(0.94, 1.06); rd = BallReading(cx, 150.0, 1000, 20, 20, diam, fd, math.degrees(math.atan2(l + w.rng.gauss(0, 0.6), f)) + w.rng.gauss(0, 1.2), False)
        if rd is None and w.rng.random() < w.decoy:         # a green thing that is not the ball
            fd = w.rng.uniform(10, 40); rd = BallReading(120, 150.0, 800, 18, 18, 8.0, fd, w.rng.uniform(-25, 25), False, "dim")
        return ("pic", rd)


class Bot:
    use_pick = False
    def __init__(self, w): self.w = w; self.bumped = False
    def _t(self, s): self.w.t += s + self.w.overhead_s
    def walk(self, secs):
        w = self.w; self._t(secs); w.bumped = False
        d = max(0.0, w.v * (secs - w.dead) + w.rng.gauss(0, w.walk_sd_in)); w.h += w.rng.gauss(0, w.drift_sd); w.advance(d); self.bumped = w.bumped; return "ok"
    def turn(self, deg, secs):
        w = self.w; self._t(secs); sgn = 1 if deg > 0 else -1
        gain = max(0.15, w.rng.gauss(1.0, w.pulse_sd)) if abs(deg) < 25 else w.turn_gain_long * w.rng.uniform(0.85, 1.15)
        w.h -= sgn * abs(deg) * gain; return "ok"
    def back(self, secs):
        w = self.w; self._t(secs); w.advance(-2.2 * secs); return "ok"
    def three_point_turn(self, deg, back_s, fwd_s): self.back(back_s); return self.turn(deg, abs(deg) / 6.0)
    def punt(self):
        w = self.w; self._t(1.5); f, l = w.rel(); b = math.degrees(math.atan2(l, max(f, .1)))
        p = w.p_hit if 2.3 <= f <= 4.1 else (0.05 if f <= 4.8 else 0.0)          # real reach: hits at 2.7-3.8 in; a ball at 4.5-5 in was "just out of reach" (2026-10-25). Beyond 4.1 in: almost never.
        p *= 1.0 if abs(b) <= 10 else 0.6
        if w.rng.random() < p:
            w.punted = True; w.bx, w.by = w.slide(w.bx, w.by, w.h + w.rng.gauss(0, 10), w.rng.uniform(14, 26))
        elif w.rng.random() < 0.3:                          # a miss that still shoves it
            w.bx, w.by = w.slide(w.bx, w.by, w.h + w.rng.gauss(0, 30), w.rng.uniform(1, 6))
        return "ok"
    def battery_ok(self): return True
    def claw_pose(self, pan, lift): self.w.t += abs(pan - self.w.pan) / 60.0 + 0.3; self.w.pan = pan; return "ok"
    def sit_down(self): self.w.t += 4.5; return "ok"
    def stand_from_sit(self): self.w.t += 2.5; return "ok"


_scorer = None
def run_episode(settings, family, seed, cal=None, falls=True, max_punts=1, max_seconds=None):
    """One simulated attempt with `settings` (a full punt-settings dict); returns (score, outcome code, seconds, family, stats dict)."""
    cal = cal if cal is not None else load_cal()
    rng = random.Random(seed); w = World(rng, family, cal)
    return _attempt(w, rng, settings, family, falls, max_punts, max_seconds)


SESSION_REST_S = 5.0                                           # the goal's rest between attempts (rest_between_s)


def run_session(settings, family, seed, cal=None, n_att=6, falls=True):
    """A session as he runs it (owner, 2026-11-02: the ball is not put back between attempts, he finds it on his own): one world, `n_att` attempts, the ball and the robot where the last
    attempt left them. The first attempt starts from a `family` situation; the later ones are labelled "chained". Returns the list of per-attempt results."""
    cal = cal if cal is not None else load_cal()
    rng = random.Random(seed); w = World(rng, family, cal); out = []
    for k in range(n_att):
        out.append(_attempt(w, rng, settings, family if k == 0 else "chained", falls, 1))
        w.t += SESSION_REST_S; w.pan = 0.0
    return out


def _attempt(w, rng, settings, family, falls, max_punts, max_seconds=None):
    with patched():
        return _attempt_patched(w, rng, settings, family, falls, max_punts, max_seconds)


def _attempt_patched(w, rng, settings, family, falls, max_punts, max_seconds=None):
    global _scorer
    from pi_pipeline.goals.ball_punt import BallPunt
    _scorer = _scorer or BallPunt()
    w.punted = False; w.bumped = False
    bot, cam, trace = Bot(w), Camera(w), []; planner = bc.ChasePlanner(rng=random.Random(rng.random()))      # the search-side coin follows the attempt's own seed
    full = dict(settings); full.update(PINNED); ps.apply(bc, {k: v for k, v in full.items() if k in ps.SPEC})
    t0 = w.t
    try:
        ended = bc.run_chase(bot, cam, lambda: False, planner=planner, max_punts=max_punts, max_seconds=max_seconds or (75.0 if max_punts == 1 else 75.0 + 40.0 * (max_punts - 1)), trace=trace, after_punt_look=True, pace=StubPace(),
                             clock=lambda: w.t, sleep=lambda s: setattr(w, "t", w.t + s), say=lambda m: None,
                             wall_check=lambda pic, ball: w.wall_reading(ball))
    except Exception as e:  # a crash in the chase is a result too
        return 0.0, "crash:" + type(e).__name__, w.t, family, {}
    still_long = max([e["seconds"] for e in trace if e.get("kind") == "still"] or [0.0])
    if falls:                                               # standing still too long lets the legs go (docs/STATUS.md item 14): 8% a second beyond 7 s, on the longest wait
        extra = sum(max(0.0, e["seconds"] - 7.0) for e in trace if e.get("kind") == "still")
        if rng.random() < min(0.9, 0.08 * extra): ended = "fell"
    out = _scorer.score(AttemptResult(ended, round(w.t - t0, 1), trace, {"punt_log": list(planner.punt_log), "walk_log": list(planner.walk_log), "back_s": round(planner.back_s, 1)}), full)
    sc = out.score if out.score is not None else 0.2
    firsts = [e["t"] for e in trace if (e.get("kind") == "look" and e.get("ball")) or (e.get("kind") == "claw_seen" and not e.get("after_punt"))]
    punts = [e["t"] for e in trace if e.get("kind") == "act" and e.get("act") == "punt"]
    seen_t = sorted([e["t"] for e in trace if (e.get("kind") == "look" and e.get("ball")) or (e.get("kind") == "claw_seen")])
    reacq = []                                              # seconds from the end of each punt to the next sighting of the ball (None: never seen again)
    for i, pt in enumerate(punts):
        nxt = next((x for x in seen_t if x > pt + 0.5), None); lim = punts[i + 1] if i + 1 < len(punts) else 1e9
        reacq.append(round(nxt - pt, 1) if nxt is not None and nxt < lim + 1e-9 else None)
    return float(sc), out.code, w.t - t0, family, {"hit": w.punted, "still_max": still_long, "first_seen": (firsts[0] if firsts else None), "punts": len(punts), "reacquire_s": reacq}
