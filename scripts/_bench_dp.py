"""Micro-benchmark: where does the Tier-1 DP time actually go?"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np

from raceiq.config import load_rules
from raceiq.pipeline import build_replay

rules = load_rules()
r = build_replay("Melbourne", 2026, "R", rules)
segs = r.segments
print("stages:", len(segs))

# how many consecutive-runs of (kind, key_accel)?
runs = 1
for a, b in zip(segs, segs[1:]):
    if (a.kind, a.is_key_acceleration) != (b.kind, b.is_key_acceleration):
        runs += 1
print("kind-runs (candidate stage count):", runs)

n = 40
A = 6
F = np.random.rand(n)
lo = np.random.randint(-3, 4, size=A)
frac = np.random.rand(A)
dT = np.random.rand(A)
base = np.arange(n)
pad = 5
BIG = 1e9


def timeit(fn, reps=2000):
    fn()
    t0 = time.perf_counter()
    for _ in range(reps):
        fn()
    return (time.perf_counter() - t0) / reps * 1e6


# variant 1: current (concat each iter)
def v1():
    Fpad = np.concatenate([np.full(pad, BIG), F, np.full(pad, BIG)])
    idx_lo = base[None, :] + pad + lo[:, None]
    idx_hi = idx_lo + 1
    vals = (1.0 - frac)[:, None] * Fpad[idx_lo] + frac[:, None] * Fpad[idx_hi]
    cand = vals + dT[:, None]
    best_a = np.argmin(cand, axis=0)
    return cand[best_a, base]


# variant 2: preallocated buffer + precomputed indices/weights
buf = np.full(n + 2 * pad, BIG)
IDX_LO = (base[None, :] + pad + lo[:, None]).astype(np.intp)
IDX_HI = IDX_LO + 1
W_LO = (1.0 - frac)[:, None]
W_HI = frac[:, None]
DT = dT[:, None]


def v2():
    buf[pad:pad + n] = F
    cand = W_LO * buf[IDX_LO] + W_HI * buf[IDX_HI] + DT
    best_a = np.argmin(cand, axis=0)
    return cand[best_a, base]


# variant 3: preallocated, no argmin (frontier only, min reduction)
def v3():
    buf[pad:pad + n] = F
    cand = W_LO * buf[IDX_LO] + W_HI * buf[IDX_HI] + DT
    return cand.min(axis=0)


# variant 4: integer shifts only (no interpolation)
IDX = IDX_LO


def v4():
    buf[pad:pad + n] = F
    cand = buf[IDX] + DT
    return cand.min(axis=0)


for name, fn in [("v1 concat+interp+argmin", v1), ("v2 prealloc+interp+argmin", v2),
                 ("v3 prealloc+interp+min", v3), ("v4 prealloc+int+min", v4)]:
    us = timeit(fn)
    print(f"  {name:32s} {us:7.2f} us/stage -> {us*len(segs)/1000:7.2f} ms for {len(segs)} stages")
