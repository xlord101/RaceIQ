"""Integer-shift gather at various grid resolutions: cost and quantisation error."""
import time

import numpy as np

BIG = 1e15


def timeit(fn, reps=400):
    fn()
    t0 = time.perf_counter()
    for _ in range(reps):
        fn()
    return (time.perf_counter() - t0) / reps * 1e6


for n in (40, 101, 201, 401, 801):
    A, pad = 5, 40
    F = np.random.rand(n)
    lo = np.random.randint(-30, 30, size=A).astype(np.intp)
    dT = np.random.rand(A)
    buf = np.full(n + 2 * pad + 2, BIG)
    base = np.arange(n)
    IDX = (base[None, :] + pad + lo[:, None]).astype(np.intp)
    DT = dT[:, None]

    def step():
        buf[pad:pad + n] = F
        return (buf[IDX] + DT).min(axis=0)

    us = timeit(step)
    print(f"  n={n:4d}  {us:6.2f} us/stage -> {us*519/1000:6.2f} ms / 519 stages")

# quantisation error: Melbourne-like per-segment energy vs grid resolution
print()
for bins in (40, 101, 401, 801):
    window = 4.0
    bin_size = window / (bins - 1)
    rng = np.random.default_rng(0)
    e_seg = rng.uniform(0.01, 0.06, size=500)          # typical 10 m deploy energy
    err = np.round(e_seg / bin_size) * bin_size - e_seg
    print(f"  bins={bins:4d} bin={bin_size*1000:6.2f} kJ  "
          f"|mean err|={np.abs(err).mean()*1000:6.2f} kJ  "
          f"random-walk drift={np.sqrt((err**2).sum())*1000:7.1f} kJ  "
          f"({np.sqrt((err**2).sum())/window*100:4.1f}% of window)")
