"""Real-world transfer layer: F1 2026 strategy applied to other domains.

The EV-bus solver is the flagship transfer (spec Section 8, PM e-Bus Sewa).
It reuses the same energy-price / posture logic as the F1 path, driven by
``config/ev_bus.json`` instead of ``config/rules_2026.json``.
"""

from raceiq.transfer.ev_bus import BUS_POSTURES, BusState, EVBusSolver

__all__ = ["EVBusSolver", "BusState", "BUS_POSTURES"]
