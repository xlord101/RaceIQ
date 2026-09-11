"""Optimise the Tier-1 sweep: preallocated buffers, float32, take(out=)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np

from raceiq.config import load_rules
from raceiq.optimize import tier1_dp as t1
from raceiq.pipeline import build_replay

rules = load_rules()
segs = build_replay("Melbourne", 2026, "R", rules).segments
prog = t1.precompile(segs, rules)
n, pad, A = prog.n_grid, prog.pad, prog.n_actions
stages = prog.stages
print("n_grid=%d pad=%d A=%d stages=%d" % (n, pad, A, len(stages)))

BIG = t1._BIG
idx32 = [s.idx.astype(np.int32) for s in stages]


def run(fn, reps=9):
    fn()
    ts = []
    for _ in range(reps):
        s = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - s) * 1000)
    return min(ts), sorted(ts)[len(ts) // 2]


def v_take_add_min():
    F = np.full(n, BIG)
    F[n - 1] = 0.0
    buf = np.full(n + 2 * pad + 2, BIG)
    C = np.empty((A, n))
    cand = np.empty((A, n))
    for i, st in enumerate(stages):
        buf[pad:pad + n] = F
        np.add(buf[st.idx], st.dt, out=cand)
        np.min(cand, axis=0, out=F)
    return F


def v_direct():
    F = np.full(n, BIG)
    F[n - 1] = 0.0
    buf = np.full(n + 2 * pad + 2, BIG)
    for i, st in enumerate(stages):
        buf[pad:pad + n] = F
        cand = buf[st.idx] + st.dt
        F = cand.min(axis=0)
    return F


def v_take_out():
    F = np.full(n, BIG)
    F[n - 1] = 0.0
    buf = np.full(n + 2 * pad + 2, BIG)
    cand = np.empty((A, n))
    for i, st in enumerate(stages):
        buf[pad:pad + n] = F
        np.take(buf, st.idx, out=cand)
        cand += st.dt
        np.min(cand, axis=0, out=F)
    return F


def v_f32():
    F = np.full(n, np.float32(BIG))
    F[n - 1] = 0.0
    buf = np.full(n + 2 * pad + 2, np.float32(BIG))
    cand = np.empty((A, n), dtype=np.float32)
    dt32 = [s.dt.astype(np.float32) for s in stages]
    for i, st in enumerate(stages):
        buf[pad:pad + n] = F
        np.take(buf, st.idx, out=cand)
        cand += dt32[i]
        np.min(cand, axis=0, out=F)
    return F


for name, fn in [("v_direct (current)", v_direct),
                 ("v_take_add_min", v_take_add_min),
                 ("v_take_out + in-place", v_take_out),
                 ("v_f32 take_out", v_f32)]:
    b, m = run(fn)
    print(f"  {name:24s} best {b:6.2f} ms | med {m:6.2f} ms")

F64 = v_direct()
F32 = v_f32()
print("  float32 vs float64 max abs diff on reachable states: %.3e"
      % np.abs(F64[F64 < 1e6] - F32[F64 < 1e6].astype(np.float64)).max())
