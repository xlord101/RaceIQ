#!/usr/bin/env python
"""Pre-cache every demo race so the whole pipeline runs offline.

    python scripts/pre_cache.py
    python scripts/pre_cache.py --events Melbourne Monza --no-openf1

Writes ``data/cache_manifest.json`` which the UI reads to display an honest
"CACHED / OFFLINE" badge.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raceiq.config import load_circuits  # noqa: E402
from raceiq.ingest import cache_status, pre_cache_sessions  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pre-cache RaceIQ race data.")
    ap.add_argument(
        "--events", nargs="*", default=None,
        help="Circuit keys; defaults to config/circuits.json demo_order.",
    )
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--session", default="R")
    ap.add_argument("--no-openf1", action="store_true", help="Skip OpenF1 downloads.")
    ap.add_argument("--status", action="store_true", help="Print cache status and exit.")
    args = ap.parse_args(argv)

    if args.status:
        st = cache_status()
        print(f"data dir     : {st['data_dir']}")
        print(f"manifest     : {'present' if st['manifest_present'] else 'MISSING'}")
        print(f"generated    : {st.get('generated_utc')}")
        for k, v in st["sessions"].items():
            flag = "sim-only" if v["simulation_only"] else ("cached" if v["fastf1"] else "FAILED")
            print(
                f"  {k:<12} {flag:<9} drivers={v['drivers']:<3} "
                f"tel={v['telemetry_samples']:<7} openf1={len(v['openf1_endpoints'])}"
            )
        return 0

    events = args.events
    if not events:
        from raceiq.config import config_dir
        import json

        with (config_dir() / "circuits.json").open(encoding="utf-8") as fh:
            events = json.load(fh).get("demo_order", [])
    if not events:
        events = list(load_circuits().keys())

    print(f"Pre-caching {len(events)} events: {', '.join(events)}")
    manifest = pre_cache_sessions(
        events,
        year=args.year,
        session=args.session,
        with_openf1=not args.no_openf1,
    )

    ok = 0
    for key, rec in manifest.get("sessions", {}).items():
        if rec.get("fastf1"):
            ok += 1
            print(
                f"  OK   {key:<12} drivers={rec.get('drivers')} "
                f"laps={rec.get('total_laps')} tel_samples={rec.get('telemetry_samples')}"
            )
        else:
            print(f"  FAIL {key:<12} {rec.get('error', 'unknown')[:90]}")
    print(f"\n{ok}/{len(manifest.get('sessions', {}))} events cached → data/cache_manifest.json")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
