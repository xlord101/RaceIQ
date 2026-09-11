"""ERS mode classification from public telemetry.

2026 has **only** the MGU-K (MGU-H deleted). The public feed carries no ERS-mode
channel (Nitrous devlog, 31 Mar 2026: "Energy Modes ... not yet available through
the API"), so the mode is **inferred** from throttle, brake, speed and the
estimated SoC.
"""

from __future__ import annotations

from typing import Optional

from raceiq.types import SocState

__all__ = ["ErsClassifier", "ERS_MODES"]

ERS_MODES = ("Harvest", "Balance", "Deploy")


class ErsClassifier:
    """Rule-based ERS mode label: ``Harvest`` / ``Balance`` / ``Deploy``.

    Rules (all thresholds are configurable via the physics block):

    * ``Harvest``  - braking, or off-throttle while the battery has headroom.
    * ``Deploy``   - high throttle at speed with usable charge, or clipping
      (driver wants power the battery cannot give).
    * ``Balance``  - everything else: part throttle, or a full battery so no
      recovery is possible.
    """

    def __init__(
        self,
        soc_window_mj: float = 4.0,
        deploy_throttle: float = 0.85,
        deploy_min_speed_kph: float = 80.0,
        harvest_soc_headroom_mj: float = 0.15,
    ) -> None:
        self.soc_window_mj = float(soc_window_mj)
        self.deploy_throttle = float(deploy_throttle)
        self.deploy_min_speed_kph = float(deploy_min_speed_kph)
        self.harvest_soc_headroom_mj = float(harvest_soc_headroom_mj)

    def classify(
        self,
        soc_state: SocState,
        throttle: float = 0.0,
        brake: float = 0.0,
        speed_kph: Optional[float] = None,
    ) -> str:
        """Return ``"Harvest"``, ``"Balance"`` or ``"Deploy"``.

        Parameters
        ----------
        soc_state:
            Current observer output; only ``soc_mj`` and ``clipping_flag`` are used.
        throttle:
            Normalised 0-1.
        brake:
            0 or 1 (or a 0-1 pressure).
        speed_kph:
            Current speed; optional, used for the minimum-speed gate.
        """
        soc = float(soc_state.soc_mj)
        headroom = self.soc_window_mj - soc

        if brake > 0.0 and headroom > self.harvest_soc_headroom_mj:
            return "Harvest"

        if soc_state.clipping_flag:
            # Flat out with no electrical power left: the driver wants to deploy.
            return "Deploy"

        if (
            throttle >= self.deploy_throttle
            and soc > self.harvest_soc_headroom_mj
            and (speed_kph is None or speed_kph >= self.deploy_min_speed_kph)
        ):
            return "Deploy"

        if throttle < 0.35 and headroom > self.harvest_soc_headroom_mj:
            return "Harvest"

        return "Balance"
