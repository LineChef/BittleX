"""Timeline model of OpenCatEsp32 executing a stream of joint commands.

Traced from source 2026-09-22 (reaction.h / motion.h / moduleManager.h):

  m  (T_INDEXED_SEQUENTIAL_ASC): per joint, in the order sent,
     transform(target, 1, speed 1) -> one 1-degree step per 8 ms
     (delay((DOF-offset)/2), DOF 16), then delay(10); then a final
     transform at transformSpeed 2 (already there: one 8 ms iteration).
  i  (T_INDEXED_SIMULTANEOUS_ASC): one transform(target, 1, transformSpeed=2)
     -> round(maxDiff/2)+1 iterations of 8 ms, all joints cosine-eased together.
  ifast: `i` with transformSpeed 0 (needs a firmware change; one iteration).

Backlog (read_serial()): the firmware slurps every waiting byte and the
newline strip truncates at the first command -- the OLDEST waiting command
runs, the rest are dropped.

Used by the env (CMD_PATH knob, training + eval) and resilience_joint_cmd.py.
"""
import numpy as np

ITER_S = 0.008          # transform() per-iteration delay: (DOF 16 - 0) / 2 ms
SEQ_JOINT_DELAY_S = 0.010
READ_DELAY_S = 0.001
BAUD_BYTES_PER_S = 115200 / 10.0
CMD_BYTES = 45          # typical "m8 50 12 0 ..." line incl. newline



class FirmwareCmdPath:
    """Timeline model of the BiBoard turning a stream of targets into servo output."""

    def __init__(self, mode, start_deg, extra_s=0.0):
        self.mode = mode
        self.extra_s = extra_s                           # unmodeled per-command firmware overhead
        self.out = np.asarray(start_deg, dtype=float)   # what the servos are being driven to now
        self.plan = []                                   # [(t_from, 8-vector)] queued piecewise-constant outputs
        self.busy_until = 0.0
        self.pending = []                                # [(t_arrival, t_sent, target)]
        self.executed = []                               # latency (s) of each executed command
        self.sent = 0

    def _schedule(self, t0, target):
        cur, tgt, t, plan = self.out_at_end().copy(), np.rint(target), t0, []
        if self.mode in ("i", "ifast"):
            diff = cur - tgt
            steps = 0 if self.mode == "ifast" else int(round(np.abs(diff).max() / 2.0))
            for s in range(steps + 1):
                k = 0.0 if steps == 0 else (1 + np.cos(np.pi * s / steps)) / 2
                plan.append((t, tgt + k * diff))
                t += ITER_S
        else:                                            # "m": one joint at a time, URDF order
            for j in range(8):
                d = cur[j] - tgt[j]
                steps = int(round(abs(d)))
                for s in range(steps + 1):
                    v = cur.copy()
                    v[j] = tgt[j] + (0.0 if steps == 0 else (1 + np.cos(np.pi * s / steps)) / 2 * d)
                    plan.append((t, v))
                    t += ITER_S
                cur[j] = tgt[j]
                t += SEQ_JOINT_DELAY_S
            plan.append((t, cur.copy()))                 # final transform: already there
            t += ITER_S
        self.plan.extend(plan)
        self.busy_until = t + self.extra_s

    def out_at_end(self):
        return self.plan[-1][1] if self.plan else self.out

    def _pump(self, now):
        while True:
            free = self.busy_until
            ready = [c for c in self.pending if c[0] <= max(free, now)]
            if not ready:
                return
            start = max(free, ready[0][0])
            if start > now:
                return
            batch = [c for c in self.pending if c[0] <= start]   # everything waiting at read time
            self.pending = [c for c in self.pending if c[0] > start]
            arrival, sent, target = batch[0]                     # oldest runs, rest dropped
            self.executed.append(start + READ_DELAY_S - sent)
            self._schedule(start + READ_DELAY_S, target)

    def send(self, t, target_deg):
        self.sent += 1
        self.pending.append((t + CMD_BYTES / BAUD_BYTES_PER_S, t, np.asarray(target_deg, dtype=float)))

    def output(self, t):
        self._pump(t)
        while self.plan and self.plan[0][0] <= t:
            self.out = self.plan.pop(0)[1]
        return self.out
