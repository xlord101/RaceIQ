"""RaceIQ 2026 - Energy & Overtake Intelligence.

TrackShift 2026 / Problem 1.

Core honesty statement
----------------------
There is **no public ground-truth battery telemetry** in Formula 1. State of charge
(SoC), MGU-K power, ERS mode and Active Aero state are not published: FIA
Art. 8.5 records are confidential between teams, the F1 broadcast removed the
SoC graphics, and the public APIs expose no ERS channel.

Every SoC / ERS / energy value produced by this package is therefore an
**ESTIMATE** reconstructed from public telemetry plus the FIA rulebook. Every UI
surface must carry the watermark defined in :data:`WATERMARK`.
"""

from __future__ import annotations

__version__ = "2.0.0"

WATERMARK = (
    "Estimated SoC - inferred from public telemetry + FIA rules. "
    "No public ERS/SoC telemetry exists."
)

SHORT_WATERMARK = "Estimated - not official data"

#: Prior-art citation. Adopted for framing (POMDP, Lharvest/Lderate split,
#: counter-harvest trap); implementation is original and not copied.
PRIOR_ART_CITATION = (
    "Kleisarchaki, 'Opponent State Inference Under Partial Observability: An "
    "HMM-POMDP Framework for 2026 Formula 1 Energy Strategy', arXiv:2603.01290v3 "
    "[cs.AI], 15 May 2026."
)

__all__ = ["__version__", "WATERMARK", "SHORT_WATERMARK", "PRIOR_ART_CITATION"]
