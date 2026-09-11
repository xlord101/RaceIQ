"""Debug: trace the Tier-1 value function stage by stage."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np

from raceiq.config import load_rules
from raceiq.optimize import tier1_dp as t1
from raceiq.pipeline import build_replay

rules = load_rules()
r = build_replay("Melbourne", 2026, "R", rules)
segs = r.segments

# 1) are any segment durations pathological?
d = np.array([s.duration_s for s in segs])
v = np.array([s.mean_speed_kph for s in segs])
print("duration_s  min %.4f max %.4f  | speed min %.1f max %.1f" % (d.min(), d.max(), v.min(), v.max()))
print("n nonfinite durations:", int((~np.isfinite(d)).sum()))

hor = t1.phase_durations(segs)
print("phase horizon min %.4f max %.4f" % (hor.min(), hor.max()))

# 2) inspect the action tables for the worst segment
worst = 0.0
worst_i = -1
for i, s in enumerate(segs):
    pw, dE, dT = t1.segment_actions(s, rules, horizon_s=float(hor[i]))
    if len(dT) and np.isfinite(dT).all():
        m = float(np.abs(dT).max())
        if m > worst:
            worst, worst_i = m, i
    if not np.isfinite(dT).all() or not np.isfinite(dE).all():
        print("NONFINITE table at segment", i, s.kind, s.mean_speed_kph, dE, dT)
        break
print("largest |dT| = %.4f s at segment %d" % (worst, worst_i))

# 3) run the sweep manually and watch F
prog = t1.precompile(segs, rules)
n, pad = prog.n_bins, prog.pad
F = np.full(n, t1._BIG)
start_bin = n - 1
F[start_bin] = 0.0
buf = np.full(n + 2 * pad + 2, t1._BIG)
base = np.arange(n)
for i, st in enumerate(prog.stages):
    buf[pad:pad + n] = F
    cand = st.w_lo * buf[st.idx_lo] + st.w_hi * buf[st.idx_lo + 1] + st.dt + st.pen
    F = cand.min(axis=0)
    if i in (0, 1, 2, 5, 20, 100, 300, len(prog.stages) - 1):
        print(f"stage {i:4d}  finite={int(np.isfinite(F).sum()):3d}  "
              f"<1e6: {int((F < 1e6).sum()):3d}  min={np.nanmin(F):.4f}  "
              f"F[start]={F[start_bin]:.4f}")
