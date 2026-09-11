"""Offline replay: compare RaceIQ vs Greedy vs Conservative on one circuit.

Builds a Tier-1 Pareto frontier (price of energy) for the requested circuit and
runs the three strategies through the offline race simulator, printing a table
of total time, battery floor, attack laps and net positions.

Usage:
    python scripts/run_replay.py --event Melbourne
    python scripts/run_replay.py --event Monza --laps 25 --harvest 3.3

Works fully offline. If no cached telemetry is available it falls back to a
simple physics-derived frontier so the comparison always runs; the frontier
source is printed in the header.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from raceiq.baselines import compare
from raceiq.config import load_circuits, load_rules
from raceiq.optimize import ParetoFrontier


def _physics_frontier(harvest_mj_per_lap: float) -> ParetoFrontier:
    """A simple, defensible energy<->time frontier for a circuit.

    More harvestable brake energy => a steeper (better) exchange rate. This is a
    monotonic placeholder so the replay always runs offline; a cached FastF1
    session would give the true frontier via ``solve_lap_dp``.
    """
    max_net = min(8.0, 2.0 + harvest_mj_per_lap)  # MJ absorbable in a lap
    energy = np.linspace(0.0, max_net, 6)
    base = 92.0
    gain_s = 3.0 * (harvest_mj_per_lap / 4.0)  # better circuits gain more time
    times = base - gain_s * (energy / max_net)
    return ParetoFrontier(energy, times)


def _real_frontier(event: str, harvest: float) -> tuple:
    """Build the frontier from REAL cached telemetry where possible.

    Returns ``(frontier, source)`` where ``source`` is an **honest** label.
    Previously this function imported a non-existent ``load_segments`` helper,
    swallowed the ``ImportError`` and silently returned the synthetic placeholder
    while still reporting "cached Tier-1 DP" - which overstated the evidence.
    Now the label can only say REAL when cached car telemetry was genuinely
    available and the DP actually solved on it.
    """
    try:
        from raceiq.config import load_rules
        from raceiq.ingest.fastf1_loader import get_lap_telemetry, load_fastf1_session
        from raceiq.track.segmentation import segments_from_telemetry
        from raceiq.optimize import solve_lap_dp

        rules = load_rules()
        data = load_fastf1_session(
            2026, event, "R", with_telemetry=True, allow_openf1_fallback=False
        )
        laps = getattr(data, "laps", None)
        if laps is None or not len(laps):
            return _physics_frontier(harvest), "SYNTHETIC placeholder (no cached laps)"

        # Representative driver = the one with the most timed laps.
        counts = laps.groupby("Driver").size().sort_values(ascending=False)
        tel = None
        for drv in counts.index:
            t = get_lap_telemetry(data, str(drv), resample_m=25.0)
            if len(t) > 50:
                tel = t
                break
        if tel is None:
            return _physics_frontier(harvest), "SYNTHETIC placeholder (no car telemetry)"

        lap_len = float(tel["Distance"].max()) or 5000.0
        segs = segments_from_telemetry(tel, rules, lap_length_m=lap_len)
        if not segs:
            return _physics_frontier(harvest), "SYNTHETIC placeholder (no segments)"

        frontier = solve_lap_dp(segs, rules)
        if len(frontier) > 1:
            return frontier, f"REAL telemetry (Tier-1 DP, {len(segs)} segments)"
    except Exception as exc:  # no cached session / offline
        return _physics_frontier(harvest), f"SYNTHETIC placeholder ({type(exc).__name__})"

    return _physics_frontier(harvest), "SYNTHETIC placeholder"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default="Melbourne", help="Circuit/event name")
    parser.add_argument("--laps", type=int, default=20)
    parser.add_argument(
        "--harvest",
        type=float,
        default=None,
        help="Circuit harvest potential MJ/lap (defaults from circuits.json)",
    )
    parser.add_argument("--soc", type=float, default=2.5, help="Initial SoC [MJ]")
    args = parser.parse_args(argv)

    circuits = load_circuits()
    circ = circuits.get(args.event) or circuits.get(args.event.lower())
    harvest = args.harvest
    if harvest is None:
        if circ is not None:
            harvest = float(circ.brake_harvest_potential_mj) or 3.0
        else:
            harvest = 3.0

    frontier, source = _real_frontier(args.event, harvest)

    print(f"=== RaceIQ replay: {args.event} ===")
    print(f"Frontier source : {source}  (harvest {harvest:.1f} MJ/lap)")
    if source.startswith("SYNTHETIC"):
        print("!! WARNING: NO REAL TELEMETRY for this circuit.")
        print("!! These numbers come from a placeholder frontier and are NOT evidence.")
    print(f"Laps            : {args.laps}   initial SoC {args.soc:.1f} MJ")
    print("-" * 64)

    # Rival pace = the circuit's neutral lap time (a fair, neutral competitor).
    neutral_time = float(frontier.time_for_energy(0.55 * frontier.max_energy_mj))

    comp = compare(
        frontier,
        laps=args.laps,
        initial_soc_mj=args.soc,
        circuit_harvest_potential_mj=harvest,
        rival_pace_s=neutral_time,
        pack_reset_gap_s=2.0,
    )

    # The Tier-1 DP returns TIME SAVED vs a no-ERS baseline (negative = faster),
    # whereas the synthetic placeholder returns absolute lap times (~92 s).
    # Printing a negative "race time" would be meaningless, so label the units.
    delta_mode = bool(len(frontier)) and float(np.nanmax(frontier.lap_time_s)) < 60.0
    if delta_mode:
        print("NOTE: frontier is in DELTA form (seconds saved vs a no-ERS")
        print("      baseline). More negative = faster. Valid for ranking the")
        print("      three strategies against each other, NOT a race time.")
        print("-" * 64)

    time_col = "DeltaT(s)" if delta_mode else "Time(s)"
    header = f"{'Strategy':<12}{time_col:>10}{'MinSoC':>9}{'AtkLaps':>9}{'NetPos':>8}{'FinGap':>9}"
    print(header)
    print("-" * 64)
    for name in comp.by_total_time:
        r = comp.results[name]
        print(
            f"{name:<12}{r.total_time_s:>10.2f}{r.min_soc_mj:>9.2f}"
            f"{r.attack_laps:>9}{r.net_position_delta:>8}{r.final_gap_ahead_s:>9.2f}"
        )
    print("-" * 64)
    print(f"Best by total time: {comp.best_strategy}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
