"""Deterministic vehicle physics used by the observer, the DP and the bus solver.

Everything here is a **model**, not a measurement. The parameters live in
``config/rules_2026.json::physics`` so any estimate can be re-derived under
different assumptions. No neural network is involved anywhere in this file.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

__all__ = [
    "KPH_TO_MS",
    "brake_energy_mj",
    "drag_power_kw",
    "deploy_gain",
    "harvest_energy_mj",
    "segment_duration_s",
    "steady_state_speed_gain",
    "superclip_penalty_s",
]

KPH_TO_MS = 1.0 / 3.6


def brake_energy_mj(v_in_kph: float, v_out_kph: float, mass_kg: float) -> float:
    """Kinetic energy shed between two speeds [MJ].

    ``0.5 * m * (v_in^2 - v_out^2)`` with speeds converted from km/h.
    """
    vi = max(float(v_in_kph), 0.0) * KPH_TO_MS
    vo = max(float(v_out_kph), 0.0) * KPH_TO_MS
    return 0.5 * float(mass_kg) * max(vi * vi - vo * vo, 0.0) / 1e6


def harvest_energy_mj(
    v_in_kph: float,
    v_out_kph: float,
    phys: Dict[str, float],
) -> float:
    """Recoverable energy in a braking event [MJ] under MGU-K-only rules.

    ``brake energy x harvest fraction x regen efficiency``. The 2026 car has no
    MGU-H, so all recovery is kinetic (rear axle), which is why the harvest
    ceiling is strongly circuit-dependent (Baku ~7.1 MJ, Monza ~3.3 MJ).
    """
    m = phys["car_mass_kg"]
    e = brake_energy_mj(v_in_kph, v_out_kph, m)
    return e * phys["harvest_fraction_of_brake_energy"] * phys["regen_efficiency"]


def drag_power_kw(speed_kph: float, phys: Dict[str, float]) -> float:
    """Aerodynamic + rolling resistance power at a given speed [kW]."""
    v = max(float(speed_kph), 0.0) * KPH_TO_MS
    aero = 0.5 * phys["air_density"] * phys["drag_coefficient_area"] * v ** 3
    roll = phys["rolling_resistance_coeff"] * phys["car_mass_kg"] * 9.81 * v
    return (aero + roll) / 1000.0


def segment_duration_s(length_m: float, speed_kph: float) -> float:
    """Time to cover ``length_m`` at ``speed_kph`` [s]."""
    v = max(float(speed_kph), 1e-6) * KPH_TO_MS
    return float(length_m) / v


def steady_state_speed_gain(
    power_kw: float,
    speed_kph: float,
    phys: Dict[str, float],
) -> float:
    """Speed the car eventually gains if ``power_kw`` is held [m/s].

    Solved on the *nonlinear* drag curve rather than its tangent, so the answer
    stays bounded when the extra power is large (a linearisation would happily
    predict +70 m/s mid-corner)::

        0.5*rho*CdA*(v + dv)^3 - 0.5*rho*CdA*v^3 = P_wheel

    Returns
    -------
    float
        Steady-state speed gain in m/s.
    """
    p_wheel = float(power_kw) * 1000.0 * _deploy_efficiency(phys)
    if p_wheel <= 0.0:
        return 0.0
    v = max(float(speed_kph), 1.0) * KPH_TO_MS
    k = phys["air_density"] * phys["drag_coefficient_area"]
    if k <= 1e-9:  # pragma: no cover - defensive
        return 0.0
    return float((v ** 3 + 2.0 * p_wheel / k) ** (1.0 / 3.0) - v)


def _deploy_efficiency(phys: Dict[str, float]) -> float:
    """Drivetrain x deployment efficiency (battery joules -> wheel joules)."""
    return float(phys.get("drivetrain_efficiency", 1.0)) * float(
        phys.get("deploy_efficiency", 1.0)
    )


def deploy_gain(
    power_kw: float,
    base_time_s: float,
    speed_kph: float,
    length_m: float,
    phys: Dict[str, float],
    horizon_s: float | None = None,
) -> Tuple[float, float]:
    """Time saved and battery energy spent by deploying ``power_kw``.

    Longitudinal model. Extra wheel power raises speed until the extra drag
    absorbs it::

        dv_ss = steady_state_speed_gain(...)     (nonlinear, bounded)
        tau   = m / (rho*CdA*v)                  (time constant)
        dv(t) = dv_ss * (1 - exp(-t/tau))

    ``horizon_s`` is the duration of the **acceleration phase** enclosing this
    segment (see :func:`raceiq.optimize.tier1_dp.phase_durations`). It matters
    because speed gained early on a straight keeps paying off for the rest of
    that straight - the time saved is the integral of ``dv`` over the whole
    phase, not just over this one segment. Without it, splitting a straight
    into 10 m pieces throws the carry-over away and understates the value of
    energy by roughly the number of pieces. The segment is credited its
    duration-weighted share of the phase total, so shares sum to the physically
    correct phase gain.

    Returns
    -------
    (time_saved_s, battery_energy_mj)
    """
    p = float(power_kw)
    if p <= 0.0 or base_time_s <= 0.0 or length_m <= 0.0:
        return 0.0, 0.0

    v = max(float(speed_kph), 1.0) * KPH_TO_MS
    k = phys["air_density"] * phys["drag_coefficient_area"]
    if k <= 1e-9:  # pragma: no cover - defensive
        return 0.0, 0.0

    dv_ss = steady_state_speed_gain(p, speed_kph, phys)
    if dv_ss <= 1e-9:
        return 0.0, 0.0

    # Time constant evaluated mid-way through the speed rise.
    tau = phys["car_mass_kg"] / (k * (v + 0.5 * dv_ss))
    horizon = float(horizon_s) if horizon_s and horizon_s > base_time_s else base_time_s

    # time saved = integral of (dv / v) dt over the horizon
    dt_phase = (dv_ss / v) * (horizon - tau * (1.0 - np.exp(-horizon / tau)))
    dt = float(dt_phase) * (base_time_s / horizon)

    energy_mj = p * base_time_s / 1000.0  # battery draw over this segment
    return max(float(dt), 0.0), float(energy_mj)


def superclip_penalty_s(energy_mj: float, phys: Dict[str, float]) -> float:
    """Time lost when the MGU-K recharges off the ICE at full throttle [s].

    Superclipping: the driver is flat out but the speed stops rising because
    engine power is being diverted into the battery.
    """
    return float(energy_mj) * phys["superclip_time_penalty_s_per_mj"]
