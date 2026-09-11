"""Ad-hoc smoke test for the Tier-1 DP against real cached telemetry."""
import sys

import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raceiq.config import load_rules
from raceiq.optimize.tier1_dp import precompile, segment_actions, solve_lap_dp_full
from raceiq.pipeline import build_replay
from raceiq.track.segmentation import max_legal_deploy_kw

rules = load_rules()
print("soc_bins:", rules.dp_soc_bins, "| dp_actions_kw:", rules.dp_actions_kw)
print("window:", rules.soc_window_mj, "| deploy_mj_per_lap:", rules.deploy_mj_per_lap)

for ev in ("Melbourne", "Monza"):
    r = build_replay(ev, 2026, "R", rules)
    segs = r.segments
    lap_len = segs[-1].end_m if segs else 0.0
    print(f"\n=== {ev}: {len(segs)} segments, lap_len={lap_len:.0f} m")
    kinds: dict = {}
    for s in segs:
        kinds[s.kind] = kinds.get(s.kind, 0) + 1
    print("  kinds:", kinds)
    print("  harvest potential total: %.3f MJ" % sum(s.harvest_potential_mj for s in segs))
    print("  key accel zones:", sum(1 for s in segs if s.is_key_acceleration))

    bad = 0
    for s in segs:
        lm = max_legal_deploy_kw(s.mean_speed_kph, s, rules)
        pw, dE, _ = segment_actions(s, rules)
        for p, e in zip(pw, dE):
            if e > 0 and p > lm + 1e-6:
                bad += 1
    print("  illegal deploy actions:", bad)

    prog = precompile(segs, rules)          # compile once, outside the timing
    sols = [solve_lap_dp_full(segs, rules, program=prog) for _ in range(7)]
    sol = solve_lap_dp_full(segs, rules, return_plan=True, program=prog)
    best = min(s.solve_ms for s in sols)
    med = sorted(s.solve_ms for s in sols)[len(sols) // 2]
    print("  solve_ms  best %.3f | median %.3f | with-plan %.3f" % (best, med, sol.solve_ms))
    print("  stages:", len(prog), "| actions/stage:", prog.n_actions, "| pad:", prog.pad)
    if sol.power_plan_kw is not None:
        pp = sol.power_plan_kw
        print("  plan: deploy segs %d, harvest segs %d, coast %d"
              % (int((pp > 0).sum()), int((pp < 0).sum()), int((pp == 0).sum())))
        print("  plan peak kW: %.0f" % np.nanmax(np.abs(pp)))
    f = sol.frontier
    print("  frontier pts:", len(f), "| monotonic:", f.is_monotonic())
    if len(f) >= 2:
        print("  energy range: %.3f -> %.3f MJ" % (f.energy_mj[0], f.energy_mj[-1]))
        print("  time range:   %.3f -> %.3f s" % (f.lap_time_s[0], f.lap_time_s[-1]))
        print("  exchange rate: %.4f s/MJ" % f.exchange_rate())
    else:
        print("  FRONTIER TOO SMALL", f.energy_mj[:10], f.lap_time_s[:10])
