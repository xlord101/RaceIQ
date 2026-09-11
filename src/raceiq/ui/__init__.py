"""UI layer for RaceIQ 2026 (spec Section 3).

``scenario.py`` builds the data for one frame using the real RaceIQ stack and
imports **no** Streamlit, so it is testable. ``main.py`` is the Streamlit app -
a professional pit-wall telemetry terminal: minimalist, dark, data-dense, no
emojis, with the honest "Estimated SoC" watermark.
"""

from raceiq.ui.scenario import (
    DRIVER_GRID,
    TEAM_COLOURS,
    DriverRow,
    Scenario,
    build_scenario,
)

__all__ = ["Scenario", "DriverRow", "build_scenario", "DRIVER_GRID", "TEAM_COLOURS"]
