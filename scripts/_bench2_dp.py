"""Micro-benchmark part 2: can the exact (interpolated) update fit in budget?"""
import time

import numpy as np

n, A, pad = 40, 6, 5
BIG = 1e9
F = np.random.rand(n)
lo = np.random.randint(-3, 4, size=A).astype(np.intp)
frac = np.random.rand(A)
dT = np.random.rand(A)
base = np.arange(n)

buf = np.full(n + 2 * pad + 2, BIG)
IDX_LO = base[None, :] + pad + lo[:, None]
IDX_HI = IDX_LO + 1
DT = dT[:, None]
W_LO = (1.0 - frac)[:, None]
W_HI = frac[:, None]

# fused index: (A, n, 2)
IDX_PAIR = np.stack([IDX_LO, IDX_HI], axis=2)
W_PAIR = np.stack([1.0 - frac, frac], axis=1)[:, None, :]

out = np.empty(n)
cand_buf = np.empty((A, n))


def timeit(fn, reps=3000):
    fn()
    t0 = time.perf_counter()
    for _ in range(reps):
        fn()
    return (time.perf_counter() - t0) / reps * 1e6


def v3():
    buf[pad:pad + n] = F
    cand = W_LO * buf[IDX_LO] + W_HI * buf[IDX_HI] + DT
    return cand.min(axis=0)


def v5():  # fused gather (A,n,2)
    buf[pad:pad + n] = F
    g = buf[IDX_PAIR]
    return (g * W_PAIR).sum(axis=2).min(axis=0)


def v6():  # v3 with out= to kill allocations
    buf[pad:pad + n] = F
    np.multiply(W_LO, buf[IDX_LO], out=cand_buf)
    np.add(cand_buf, W_HI * buf[IDX_HI], out=cand_buf)
    np.add(cand_buf, DT, out=cand_buf)
    return cand_buf.min(axis=0)


def v7():  # integer shift, no interpolation
    buf[pad:pad + n] = F
    return (buf[IDX_LO] + DT).min(axis=0)


def v8():  # v3 but gather on a doubled buffer via flat index (one gather)
    buf[pad:pad + n] = F
    flat = IDX_PAIR.reshape(A, 2 * n)
    g = buf[flat]
    g = g.reshape(A, n, 2)
    return (g * W_PAIR).sum(axis=2).min(axis=0)


for name, fn in [("v3 two-gather interp", v3), ("v5 fused (A,n,2)", v5),
                 ("v6 out= no-alloc", v6), ("v7 int shift", v7), ("v8 flat gather", v8)]:
    us = timeit(fn)
    print(f"  {name:24s} {us:7.2f} us/stage -> {us*519/1000:6.2f} ms / 519 stages")
