"""Real 2026 grid registry for the RaceIQ pit wall — **we are Haas**.

RaceIQ is pitched as the **Haas F1 Team** pit-wall tool: every recommendation
(ATTACK / HOLD / HARVEST / DEFEND) is made *for a Haas car* (OCO #31 or BEA #87).
This module builds the running order the tool reasons about from **real 2026
session data** cached under ``data/cache/2026``:

* **Lineup** — driver code, full name, team, official colour and car number come
  from FastF1 ``driver_info`` (real 2026 data, not invented).
* **Order** — the real median lap-time ranking from ``timing_app_data``
  (fastest first). This is a genuine pace-derived running order.
* **Gaps** — derived from that real pace: a car that is ``d`` s/lap slower than
  the car ahead is ``d * laps`` s behind after ``laps`` racing laps.

Where a circuit has **no cached telemetry** (Bahrain) or was **not raced in 2026**
(Baku), the canonical 2026 lineup is used and the grid is flagged
``simulation_only`` — the UI must label it, per ``config/circuits.json``.

Grids are **editable**: the analyst can reorder cars and/or override a gap to
re-price the bet (:func:`apply_edits`). This is a first-class feature, because
"what if we were 0.6 s behind instead of 1.4 s?" is exactly the pit-wall
question. Any edited grid is flagged ``edited=True`` so it is never mistaken for
the real one.

Prior art: arXiv:2603.01290 (cited, framing adopted, implementation original).
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "OUR_TEAM",
    "OUR_DRIVERS",
    "DEMO_CIRCUITS",
    "GridDriver",
    "GridRow",
    "Grid",
    "load_lineup",
    "real_pace",
    "build_grid",
    "apply_edits",
    "our_cars",
    "circuit_status",
]


#: The team RaceIQ represents. Every recommendation is made for one of its cars.
OUR_TEAM = "Haas F1 Team"

#: The two Haas cars (real 2026 lineup).
OUR_DRIVERS: Tuple[str, str] = ("OCO", "BEA")

#: The five demo grids (matches ``config/circuits.json`` -> ``demo_order``).
DEMO_CIRCUITS: Tuple[str, ...] = ("Melbourne", "Shanghai", "Monza", "Bahrain", "Baku")

_CACHE_ROOT = os.path.join("data", "cache", "2026")

#: Maps our circuit key -> keyword in the cached FastF1 event folder name.
_EVENT_KEYWORD: Dict[str, str] = {
    "Melbourne": "Australian",
    "Shanghai": "Chinese",
    "Monza": "Italian",
    "Bahrain": "Bahrain",
    "Baku": "Azerbaijan",
}

#: Real 2026 lineup (FastF1 ``driver_info``, Italian GP).
#: ``(code, full_name, team, colour_hex_without_hash, car_number)``
#: Used as the offline fallback when a circuit's session cache is unavailable.
CANONICAL_LINEUP: Tuple[Tuple[str, str, str, str, str], ...] = (
    ("VER", "Max VERSTAPPEN", "Red Bull Racing", "4781D7", "3"),
    ("LAW", "Liam LAWSON", "Red Bull Racing", "4781D7", "30"),
    ("NOR", "Lando NORRIS", "McLaren", "F47600", "1"),
    ("PIA", "Oscar PIASTRI", "McLaren", "F47600", "81"),
    ("LEC", "Charles LECLERC", "Ferrari", "ED1131", "16"),
    ("HAM", "Lewis HAMILTON", "Ferrari", "ED1131", "44"),
    ("RUS", "George RUSSELL", "Mercedes", "00D7B6", "63"),
    ("ANT", "Kimi ANTONELLI", "Mercedes", "00D7B6", "12"),
    ("ALO", "Fernando ALONSO", "Aston Martin", "229971", "14"),
    ("STR", "Lance STROLL", "Aston Martin", "229971", "18"),
    ("GAS", "Pierre GASLY", "Alpine", "00A1E8", "10"),
    ("COL", "Franco COLAPINTO", "Alpine", "00A1E8", "43"),
    ("ALB", "Alexander ALBON", "Williams", "1868DB", "23"),
    ("SAI", "Carlos SAINZ", "Williams", "1868DB", "55"),
    ("LIN", "Arvid LINDBLAD", "Racing Bulls", "6C98FF", "41"),
    ("TSU", "Yuki TSUNODA", "Racing Bulls", "6C98FF", "22"),
    ("HUL", "Nico HULKENBERG", "Audi", "F50537", "27"),
    ("BOR", "Gabriel BORTOLETO", "Audi", "F50537", "5"),
    ("OCO", "Esteban OCON", "Haas F1 Team", "9C9FA2", "31"),
    ("BEA", "Oliver BEARMAN", "Haas F1 Team", "9C9FA2", "87"),
    ("PER", "Sergio PEREZ", "Cadillac", "909090", "11"),
    ("BOT", "Valtteri BOTTAS", "Cadillac", "909090", "77"),
)


def _norm_colour(c: str) -> str:
    """Normalise a FastF1 colour to ``#RRGGBB`` (FastF1 omits the ``#``)."""
    c = (c or "").strip().lstrip("#")
    return f"#{c}" if c else "#8A93A0"


@dataclass(frozen=True)
class GridDriver:
    """One real 2026 entrant."""

    code: str
    name: str
    team: str
    colour: str
    number: str
    pace_s: float = 0.0  # real median lap time [s]; 0 = unknown

    @property
    def is_ours(self) -> bool:
        """True for a Haas car — the cars we actually advise."""
        return self.team == OUR_TEAM


@dataclass(frozen=True)
class GridRow:
    """One car in the running order, with its gaps."""

    position: int
    code: str
    name: str
    team: str
    colour: str
    number: str
    pace_s: float
    interval_s: float  # gap to the leader
    gap_ahead_s: float  # gap to the car directly ahead
    is_ours: bool

    @property
    def driver(self) -> str:
        """Alias used by the UI tower renderer."""
        return self.code


@dataclass
class Grid:
    """A complete, ordered grid for one circuit at one lap."""

    circuit: str
    lap: int
    rows: List[GridRow]
    data_status: str  # cached_2026 | no_fastf1_telemetry | not_raced_yet_2026
    simulation_only: bool
    source: str  # fastf1_cache | canonical_lineup
    edited: bool = False
    note: str = ""

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def order(self) -> List[str]:
        """Driver codes P1..Pn."""
        return [r.code for r in self.rows]

    def row(self, code: str) -> Optional[GridRow]:
        for r in self.rows:
            if r.code == code:
                return r
        return None

    def car_ahead(self, code: str) -> Optional[GridRow]:
        """The car directly ahead of ``code``, if any."""
        for i, r in enumerate(self.rows):
            if r.code == code and i > 0:
                return self.rows[i - 1]
        return None

    def as_rows(self) -> List[Dict[str, object]]:
        """JSON-friendly projection."""
        return [
            {
                "position": r.position,
                "code": r.code,
                "driver": r.code,
                "name": r.name,
                "team": r.team,
                "colour": r.colour,
                "number": r.number,
                "pace_s": r.pace_s,
                "interval_s": r.interval_s,
                "gap_ahead_s": r.gap_ahead_s,
                "is_ours": r.is_ours,
            }
            for r in self.rows
        ]


# --------------------------------------------------------------------------
# Loading real data
# --------------------------------------------------------------------------

def _race_dir(circuit: str) -> Optional[str]:
    """Locate the cached race folder for ``circuit``, if it exists."""
    keyword = _EVENT_KEYWORD.get(circuit)
    if not keyword or not os.path.isdir(_CACHE_ROOT):
        return None
    for path in sorted(glob.glob(os.path.join(_CACHE_ROOT, "*", "*_Race"))):
        if keyword.lower() in os.path.basename(os.path.dirname(path)).lower():
            return path
    return None


def load_lineup(circuit: str) -> Tuple[List[GridDriver], str]:
    """Real 2026 lineup for ``circuit``.

    Prefers the cached FastF1 ``driver_info``; falls back to the canonical 2026
    lineup. Returns ``(drivers, source)`` where source is ``fastf1_cache`` or
    ``canonical_lineup``.
    """
    rd = _race_dir(circuit)
    if rd:
        f = os.path.join(rd, "driver_info.ff1pkl")
        if os.path.exists(f):
            try:
                info = pd.read_pickle(f)["data"]
                out: List[GridDriver] = []
                for _num, v in info.items():
                    out.append(
                        GridDriver(
                            code=str(v.get("Tla", "")).upper(),
                            name=str(v.get("FullName", "")),
                            team=str(v.get("TeamName", "")),
                            colour=_norm_colour(str(v.get("TeamColour", ""))),
                            number=str(v.get("RacingNumber", "")),
                        )
                    )
                out = [d for d in out if d.code]
                if len(out) >= 15:
                    return out, "fastf1_cache"
            except Exception:  # pragma: no cover - defensive
                pass
    return [
        GridDriver(code=c, name=n, team=t, colour=_norm_colour(col), number=num)
        for c, n, t, col, num in CANONICAL_LINEUP
    ], "canonical_lineup"


def real_pace(circuit: str) -> Dict[str, float]:
    """Real median lap time [s] per driver code, from cached lap timing.

    Returns ``{}`` when the circuit has no usable telemetry (the caller then
    falls back to a deterministic pace model and must label the grid).
    """
    rd = _race_dir(circuit)
    if not rd:
        return {}
    f = os.path.join(rd, "timing_app_data.ff1pkl")
    if not os.path.exists(f):
        return {}
    try:
        df = pd.read_pickle(f)["data"]
        if "LapTime" not in df.columns:
            return {}
        sub = df[df["LapTime"].notna()].copy()
        if not len(sub):
            return {}
        sub["lt"] = pd.to_timedelta(sub["LapTime"]).dt.total_seconds()
        # plausible flying laps only
        sub = sub[(sub["lt"] > 40.0) & (sub["lt"] < 200.0)]
        if not len(sub):
            return {}
        med = sub.groupby("Driver")["lt"].median()

        # map car number -> driver code
        num_to_code: Dict[str, str] = {}
        di = os.path.join(rd, "driver_info.ff1pkl")
        if os.path.exists(di):
            try:
                for _n, v in pd.read_pickle(di)["data"].items():
                    num_to_code[str(v.get("RacingNumber", ""))] = str(
                        v.get("Tla", "")
                    ).upper()
            except Exception:  # pragma: no cover - defensive
                pass

        out: Dict[str, float] = {}
        for num, val in med.items():
            code = num_to_code.get(str(num))
            if code:
                out[code] = float(val)
        return out
    except Exception:  # pragma: no cover - defensive
        return {}


def circuit_status(circuit: str) -> Tuple[str, bool]:
    """``(data_status, simulation_only)`` for a circuit, honouring the config."""
    try:
        from raceiq.config import load_circuits

        c = load_circuits().get(circuit)
        if c is not None:
            return (
                str(getattr(c, "data_status", "unknown")),
                bool(getattr(c, "simulation_only", False)),
            )
    except Exception:  # pragma: no cover - defensive
        pass
    return ("unknown", False)


# --------------------------------------------------------------------------
# Building / editing grids
# --------------------------------------------------------------------------

#: Realistic bounds for the gap between two adjacent cars, in seconds.
_MIN_ADJACENT_GAP_S = 0.15
_MAX_ADJACENT_GAP_S = 4.00


def build_grid(
    circuit: str = "Melbourne",
    lap: int = 34,
    pace: Optional[Dict[str, float]] = None,
) -> Grid:
    """Build the real running order for ``circuit`` at ``lap``.

    Ordering is the real pace ranking (fastest first, from
    :func:`real_pace`); each car's gap to the car ahead is its real pace
    deficit accumulated over ``lap`` laps, clamped to a plausible racing range.

    Cars with **no** real pace are placed at the back in lineup order and given
    a nominal deficit, so the grid is always complete and deterministic.
    """
    drivers, source = load_lineup(circuit)
    if pace is None:
        pace = real_pace(circuit)

    paced = [replace(d, pace_s=float(pace.get(d.code, 0.0))) for d in drivers]
    known = [d for d in paced if d.pace_s > 0.0]
    unknown = [d for d in paced if d.pace_s <= 0.0]

    known.sort(key=lambda d: d.pace_s)
    has_pace = bool(known)
    if not known:  # pragma: no cover - no telemetry at all
        # No telemetry: use the canonical ENTRY order (a competitive order),
        # never alphabetical - an alphabetical grid would be meaningless.
        idx = {c: i for i, (c, *_rest) in enumerate(CANONICAL_LINEUP)}
        known = sorted(paced, key=lambda d: idx.get(d.code, 999))
        unknown = []

    # Backmarkers without a real lap time: nominal +0.35 s/lap each.
    base = known[-1].pace_s if known else 90.0
    for i, d in enumerate(unknown):
        unknown[i] = replace(d, pace_s=round(base + 0.35 * (i + 1), 3))
    ordered = known + unknown

    # Deterministic, realistic field spread for circuits with no telemetry
    # (a 22-car field separated by 0.15 s each is not a race).
    n_cars = len(ordered)
    fallback_gaps = [0.0] + [
        round(0.45 + 0.60 * ((i * 37) % 11) / 10.0, 3) for i in range(1, n_cars)
    ]

    rows: List[GridRow] = []
    interval = 0.0
    prev_pace = ordered[0].pace_s
    for i, d in enumerate(ordered):
        if i == 0:
            gap_ahead = 0.0
        elif not has_pace:
            gap_ahead = float(fallback_gaps[i])
        else:
            deficit = max(d.pace_s - prev_pace, 0.0)
            gap_ahead = float(
                np.clip(deficit * lap, _MIN_ADJACENT_GAP_S, _MAX_ADJACENT_GAP_S)
            )
        interval += gap_ahead
        rows.append(
            GridRow(
                position=i + 1,
                code=d.code,
                name=d.name,
                team=d.team,
                colour=d.colour,
                number=d.number,
                pace_s=round(float(d.pace_s), 3),
                interval_s=round(float(interval), 3),
                gap_ahead_s=round(float(gap_ahead), 3),
                is_ours=d.is_ours,
            )
        )
        prev_pace = d.pace_s

    data_status, sim_only = circuit_status(circuit)
    note = ""
    if source == "canonical_lineup":
        note = (
            "Lineup is the canonical 2026 entry list; no cached telemetry for "
            "this circuit, so the order is representative, not measured."
        )
    if sim_only:
        note = (note + " ").strip() + " Circuit not raced in 2026 - SIMULATION."

    return Grid(
        circuit=circuit,
        lap=int(lap),
        rows=rows,
        data_status=data_status,
        simulation_only=sim_only,
        source=source,
        note=note.strip(),
    )


def apply_edits(
    grid: Grid,
    order: Optional[Sequence[str]] = None,
    gap_overrides: Optional[Dict[str, float]] = None,
) -> Grid:
    """Return a new, **edited** grid (the analyst moved cars around).

    Parameters
    ----------
    order:
        Full or partial new running order by driver code. Codes not listed keep
        their relative order after the listed ones.
    gap_overrides:
        ``{driver_code: gap_to_car_ahead_s}`` forcing a specific gap.
    """
    rows = list(grid.rows)
    if order:
        wanted = [c.upper() for c in order]
        by_code = {r.code: r for r in rows}
        ordered = [by_code[c] for c in wanted if c in by_code]
        rest = [r for r in rows if r.code not in wanted]
        rows = ordered + rest

    rebuilt: List[GridRow] = []
    interval = 0.0
    for i, r in enumerate(rows):
        if i == 0:
            gap_ahead = 0.0
        elif gap_overrides and r.code in gap_overrides:
            gap_ahead = float(max(gap_overrides[r.code], 0.0))
        else:
            gap_ahead = float(r.gap_ahead_s)
        interval += gap_ahead
        rebuilt.append(
            replace(
                r,
                position=i + 1,
                gap_ahead_s=round(gap_ahead, 3),
                interval_s=round(float(interval), 3),
            )
        )

    return replace(
        grid,
        rows=rebuilt,
        edited=True,
        note=(grid.note + " Grid edited by the analyst.").strip(),
    )


def our_cars(grid: Grid) -> List[GridRow]:
    """The Haas cars in this grid, in running order."""
    return [r for r in grid.rows if r.is_ours]
