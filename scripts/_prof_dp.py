"""Where do the Tier-1 milliseconds go?"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np

from raceiq.config import load_rules
from raceiq.optimize import tier1_dp as t1
from raceiq.optimize.frontier import ParetoFrontier
from raceiq.pipeline import build_replay

rules = load_rules()
segs = build_replay("Melbourne", 2026, "R", rules).segments

t0 = time.perf_counter()
prog = t1.precompile(segs, rules)
print("compile          : %7.2f ms" % ((time.perf_counter() - t0) * 1000))

n, pad = prog.n_grid, prog.pad
print("n_grid=%d pad=%d actions=%d stages=%d" % (n, pad, prog.n_actions, len(prog)))


def sweep(store):
    F = np.full(n, t1._BIG)
    F[n - 1] = 0.0
    buf = np.full(n + 2 * pad + 2, t1._BIG)
    base = np.arange(n)
    for i, st in enumerate(prog.stages):
        buf[pad:pad + n] = F
        cand = buf[st.idx] + st.dt
        if store is None:
            F = cand.min(axis=0)
        else:
            best = np.argmin(cand, axis=0)
            F = cand[best, base]
            store[i] = best.astype(np.int16)
    return F


for _ in range(3):
    sweep(None)
best = min((lambda: (lambda s: (time.perf_counter() - s) * 1000)(time.perf_counter()))() for _ in range(1))
times = []
for _ in range(9):
    s = time.perf_counter()
    F = sweep(None)
    times.append((time.perf_counter() - s) * 1000)
print("sweep  best/med  : %7.2f / %7.2f ms" % (min(times), sorted(times)[4]))

take = np.zeros((len(prog.stages), n), dtype=np.int16)
times = []
for _ in range(9):
    s = time.perf_counter()
    F = sweep(take)
    times.append((time.perf_counter() - s) * 1000)
print("sweep+take b/med : %7.2f / %7.2f ms" % (min(times), sorted(times)[4]))

# post-processing
s = time.perf_counter()
for _ in range(50):
    valid = F < t1._FEASIBLE_MAX
    end_bins = np.flatnonzero(valid)
    net = (n - 1 - end_bins) * prog.bin_size
    raw = ParetoFrontier(net, F[end_bins])
    out = t1._resample(raw, prog.n_report)
print("post per call    : %7.3f ms" % ((time.perf_counter() - s) / 50 * 1000))

s = time.perf_counter()
for _ in range(50):
    pl = t1._recover_plan(take, prog.stages, int(np.argmin(F)))
print("recover per call : %7.3f ms" % ((time.perf_counter() - s) / 50 * 1000))
print("plan deploy/harvest/coast:",
      int((pl > 0).sum()), int((pl < 0).sum()), int((pl == 0).sum()))
