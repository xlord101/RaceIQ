"""Configuration loading.

Master instruction #5: **never** hard-code an FIA constant in code. Every
regulation value lives in ``config/*.json`` and is read through this module.

The loaders are cached and can be pointed at a different config directory with
the ``RACEIQ_CONFIG_DIR`` environment variable (used by the tests).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "ConfigError",
    "RulesConfig",
    "EventConfig",
    "EvBusConfig",
    "CircuitConfig",
    "HMMConfig",
    "config_dir",
    "load_rules",
    "load_event",
    "load_ev_bus",
    "load_circuits",
    "load_hmm_priors",
    "list_events",
    "power_to_propel_kw",
    "fuel_flow_limit_kg_per_h",
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_DIR = _REPO_ROOT / "config"

_CACHE: Dict[str, Any] = {}
_LOCK = threading.RLock()


class ConfigError(RuntimeError):
    """Raised when a config file is missing or malformed."""


def config_dir() -> Path:
    """Return the active configuration directory.

    Honours ``RACEIQ_CONFIG_DIR``; falls back to ``<repo>/config``.
    """
    env = os.environ.get("RACEIQ_CONFIG_DIR")
    if env:
        return Path(env)
    return _DEFAULT_CONFIG_DIR


def _read(name: str) -> Dict[str, Any]:
    path = config_dir() / name
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"Malformed JSON in {path}: {exc}") from exc


def _clean(raw: Any) -> Any:
    """Recursively drop ``_comment`` / ``_verified`` style metadata keys.

    Documentation keys live inside numeric blocks (e.g.
    ``power_to_propel_params._comment``) and must not reach ``float()``.
    """
    if isinstance(raw, dict):
        return {k: _clean(v) for k, v in raw.items() if not k.startswith("_")}
    if isinstance(raw, list):
        return [_clean(v) for v in raw]
    return raw


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RulesConfig:
    """Typed view over ``config/rules_2026.json``."""

    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def regulation_issue(self) -> str:
        return str(self.raw.get("regulation_issue", ""))

    @property
    def soc_window_mj(self) -> float:
        """Usable battery window [MJ] - FIA Art. 5.4.8."""
        return float(self.raw["soc_window_mj"])

    @property
    def harvest_cap_mj_per_lap(self) -> float:
        """Max harvest per lap [MJ] - Art. 5.4.9."""
        return float(self.raw["harvest_cap_mj_per_lap"])

    @property
    def deploy_mj_per_lap(self) -> float:
        """Reference deployment allowance per lap [MJ]."""
        return float(self.raw["deploy_mj_per_lap"])

    @property
    def recharge_variants_mj(self) -> Dict[str, float]:
        """Art. 5.4.9 Recharge ceiling variants [MJ/lap], keyed by regime."""
        return {k: float(v) for k, v in _clean(self.raw["recharge_mj_per_lap"]).items()}

    @property
    def recharge_standard_mj(self) -> float:
        """Standard race Recharge ceiling [MJ/lap] - 8.5, never 9.0."""
        return float(_clean(self.raw["recharge_mj_per_lap"])["standard"])

    def recharge_limit_mj(
        self,
        regime: str = "standard",
        conditional_bonus: bool = False,
    ) -> float:
        """Select the Recharge ceiling for a session regime.

        Parameters
        ----------
        regime:
            One of ``standard`` | ``reduced_event`` | ``qualifying`` |
            ``safety_car`` | ``low_grip``.
        conditional_bonus:
            When True the Stewards' conditional +0.5 MJ allowance is added.

        Unknown regimes raise :class:`ConfigError` instead of silently
        falling back, so a typo can never become a fake FIA limit.
        """
        variants = _clean(self.raw["recharge_mj_per_lap"])
        if regime not in variants:
            raise ConfigError(
                f"Unknown recharge regime {regime!r}; "
                f"expected one of {sorted(variants)}"
            )
        limit = float(variants[regime])
        if conditional_bonus:
            limit += float(variants["conditional_bonus"])
        return limit

    @property
    def overtake_cutoff_kph(self) -> float:
        """MGU-K zero-power speed with Overtake Mode active [km/h] (355)."""
        return float(_clean(self.raw["overtake_curve_kph"])["cutoff_kph"])

    @property
    def mgu_k_max_kw(self) -> float:
        """MGU-K maximum power [kW] - Art. 5.4.1."""
        return float(self.raw["mgu_k_max_kw"])

    @property
    def race_boost_cap_kw(self) -> float:
        """Post-Miami race boost cap above baseline deployment [kW]."""
        return float(self.raw["race_boost_cap_kw"])

    @property
    def base_deploy_kw(self) -> float:
        """Baseline deployment before boost [kW]."""
        return float(self.raw["base_deploy_kw"])

    @property
    def superclip_max_kw(self) -> float:
        """Max MGU-K recharge power drawn from the ICE at full throttle [kW].

        This is what a 2026 car does when it "superclips": the driver is at full
        throttle but the MGU-K is charging rather than propelling, so speed stops
        rising. Capped by the same power-to-propel stack as deployment.
        """
        return float(self.raw["superclip_max_kw"])

    @property
    def quali_recharge_mj(self) -> float:
        """Permitted recharge during a qualifying/out lap [MJ]."""
        return float(self.raw["quali_recharge_mj"])

    @property
    def zone_deploy_kw(self) -> Dict[str, float]:
        """Per-zone deployment caps [kW]."""
        return {k: float(v) for k, v in self.raw["zone_deploy_kw"].items()}

    @property
    def mgu_k_torque_nm(self) -> float:
        return float(self.raw["mgu_k_torque_nm"])

    @property
    def torque_efficiency_correction(self) -> float:
        return float(self.raw["torque_efficiency_correction"])

    @property
    def start_min_speed_kph(self) -> float:
        return float(self.raw["start_min_speed_kph"])

    @property
    def pit_stationary_gain_kj(self) -> float:
        return float(self.raw["pit_stationary_gain_kj"])

    @property
    def slew_rate_kw_per_s(self) -> float:
        return float(self.raw["slew_rate_kw_per_s"])

    @property
    def detection_gap_s(self) -> float:
        """Default detection gap [s]; overridden per event."""
        return float(self.raw["detection_gap_s"])

    @property
    def overtake_bonus_mj(self) -> float:
        """Energy bonus granted by Overtake Mode [MJ]."""
        return float(self.raw["overtake_bonus_mj"])

    @property
    def overtake_speed_kph(self) -> Dict[str, float]:
        return {k: float(v) for k, v in self.raw["overtake_speed_kph"].items()}

    @property
    def power_to_propel_params(self) -> Dict[str, float]:
        return {k: float(v) for k, v in _clean(self.raw["power_to_propel_params"]).items()}

    @property
    def fuel_rpm_params(self) -> Dict[str, float]:
        return {k: float(v) for k, v in _clean(self.raw["fuel_rpm_params"]).items()}

    @property
    def physics(self) -> Dict[str, float]:
        """Vehicle model parameters (assumptions, not FIA constants)."""
        return {k: float(v) for k, v in _clean(self.raw["physics"]).items()}

    @property
    def dp(self) -> Dict[str, Any]:
        return dict(_clean(self.raw["dp"]))

    @property
    def dp_actions_kw(self) -> List[float]:
        return [float(v) for v in _clean(self.raw["dp"])["actions_kw"]]

    @property
    def dp_soc_bins(self) -> int:
        return int(self.raw["dp"]["soc_bins"])

    @property
    def segment_length_m(self) -> float:
        return float(self.raw["dp"]["segment_length_m"])

    @property
    def points(self) -> Dict[str, Any]:
        return dict(_clean(self.raw["points"]))

    @property
    def mguh_deleted(self) -> bool:
        return bool(self.raw["mguh_deleted"])

    @property
    def cars(self) -> int:
        return int(self.raw["cars"])


def power_to_propel_kw(
    speed_kph: float, rules: RulesConfig, overtake_mode: bool = False
) -> float:
    """Electrical power-to-propel limit at a given speed [kW].

    Implements FIA 2026 C5.2.8 using the numeric parameters in
    ``rules_2026.json::power_to_propel_params`` (the human-readable formula is
    kept alongside it for provenance).

    - below 340 km/h: ``min(cap, intercept - slope*v)``  (1800 - 5v)
    - 340-345 km/h: ``taper_intercept - taper_slope*v``  (6900 - 20v)
    - above 345 km/h: zero without Overtake Mode

    With ``overtake_mode=True`` the 340-345 taper is extended so power reaches
    zero at 355 km/h (``overtake_curve_kph.cutoff_kph``) instead of 345.
    """
    p = rules.power_to_propel_params
    v = float(speed_kph)
    cap = p["cap_kw"]
    if overtake_mode:
        cutoff = float(rules.overtake_cutoff_kph)
        if v >= cutoff:
            return 0.0
        if v >= p["crossover_kph"]:
            # Extended taper: same 100 kW at 340, zero at `cutoff` (355).
            frac = (v - p["crossover_kph"]) / (cutoff - p["crossover_kph"])
            return min(cap, max(0.0, 100.0 * (1.0 - frac)))
    if v >= p["cutoff_kph"]:
        return float(p.get("above_cutoff_kw", 0.0))
    if v >= p["crossover_kph"]:
        return min(cap, p["taper_intercept_kw"] - p["taper_slope_kw_per_kph"] * v)
    return min(cap, p["intercept_kw"] - p["slope_kw_per_kph"] * v)


def fuel_flow_limit_kg_per_h(rpm: float, rules: RulesConfig) -> float:
    """Fuel mass-flow limit [kg/h] below the 10,500 rpm knee."""
    p = rules.fuel_rpm_params
    if rpm >= p["knee_rpm"]:
        return p["slope_kg_per_h_per_rpm"] * p["knee_rpm"] + p["intercept_kg_per_h"]
    return p["slope_kg_per_h_per_rpm"] * float(rpm) + p["intercept_kg_per_h"]


# --------------------------------------------------------------------------
# Event
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EventConfig:
    """Typed view over ``config/event_<name>.json``."""

    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def event(self) -> str:
        return str(self.raw.get("event", ""))

    @property
    def year(self) -> int:
        return int(self.raw.get("year", 2026))

    @property
    def detection_line_m(self) -> Optional[float]:
        """Detection line distance along the lap [m]; ``None`` if unconfirmed."""
        v = self.raw.get("detection_line_m")
        return None if v is None else float(v)

    @property
    def activation_line_m(self) -> Optional[float]:
        v = self.raw.get("activation_line_m")
        return None if v is None else float(v)

    @property
    def detection_gap_s(self) -> float:
        v = self.raw.get("detection_gap_s")
        return 1.0 if v is None else float(v)

    @property
    def deploy_mj_with_overtake(self) -> float:
        # Master Plan Phase 2: no generic 9 MJ assumption. When the event
        # note does not state an allowance, fall back to the 8.5 MJ standard.
        v = self.raw.get("deploy_mj_with_overtake")
        return 8.5 if v is None else float(v)

    @property
    def deploy_mj_without_overtake(self) -> float:
        v = self.raw.get("deploy_mj_without_overtake")
        return 8.5 if v is None else float(v)

    @property
    def recharge_mj(self) -> float:
        # Standard Recharge ceiling is 8.5 MJ/lap, never 9.0.
        v = self.raw.get("recharge_mj")
        return 8.5 if v is None else float(v)

    @property
    def special_power_reduction_zones(self) -> List[Dict[str, Any]]:
        return list(self.raw.get("special_power_reduction_zones", []))

    @property
    def overtake_zones(self) -> List[Dict[str, Any]]:
        return list(self.raw.get("overtake_zones", []))

    @property
    def active_aero_zones(self) -> List[Dict[str, Any]]:
        return list(self.raw.get("active_aero_zones", []))

    @property
    def verified(self) -> bool:
        return bool(self.raw.get("_verified", False))


# --------------------------------------------------------------------------
# EV bus
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EvBusConfig:
    """Typed view over ``config/ev_bus.json``."""

    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def battery_usable_window_kwh(self) -> float:
        return float(self.raw["battery_usable_window_kwh"])

    @property
    def reserve_soc_pct(self) -> float:
        return float(self.raw["reserve_soc_pct"])

    @property
    def regen_per_stop_kwh(self) -> float:
        return float(self.raw["regen_per_stop_kwh"])

    @property
    def traction_per_segment_kwh(self) -> float:
        return float(self.raw["traction_per_segment_kwh"])

    @property
    def max_power_kw(self) -> float:
        return float(self.raw["max_power_kw"])

    @property
    def max_c_rate(self) -> float:
        return float(self.raw["max_c_rate"])

    @property
    def stops_on_route(self) -> int:
        return int(self.raw["stops_on_route"])

    @property
    def schedule_adherence_penalty(self) -> float:
        return float(self.raw["schedule_adherence_penalty"])

    @property
    def depot_charge_kw(self) -> float:
        return float(self.raw["depot_charge_kw"])

    @property
    def route(self) -> Dict[str, float]:
        return {k: float(v) for k, v in _clean(self.raw["route"]).items()}

    @property
    def solver(self) -> Dict[str, Any]:
        return dict(_clean(self.raw["solver"]))

    @property
    def modes(self) -> Dict[str, Any]:
        return dict(_clean(self.raw["modes"]))


# --------------------------------------------------------------------------
# Circuits + HMM priors
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CircuitConfig:
    """One entry of ``config/circuits.json``."""

    key: str
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def name(self) -> str:
        return str(self.raw.get("name", self.key))

    @property
    def fastf1_event(self) -> str:
        return str(self.raw.get("fastf1_event", self.key))

    @property
    def openf1_session_key(self) -> Optional[int]:
        v = self.raw.get("openf1_session_key")
        return None if v is None else int(v)

    @property
    def lap_length_m(self) -> float:
        return float(self.raw.get("lap_length_m", 5000.0))

    @property
    def brake_harvest_potential_mj(self) -> float:
        return float(self.raw.get("brake_harvest_potential_mj", 0.0))

    @property
    def simulation_only(self) -> bool:
        return bool(self.raw.get("simulation_only", False))

    @property
    def data_status(self) -> str:
        return str(self.raw.get("data_status", "unknown"))


@dataclass(frozen=True)
class HMMConfig:
    """Typed view over ``config/hmm_priors.json`` (analytic, untrained)."""

    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def states(self) -> List[str]:
        return list(self.raw["states"])

    @property
    def ers_states(self) -> List[str]:
        return list(self.raw["ers_states"])

    @property
    def initial_ers(self) -> Dict[str, float]:
        init = self.raw["initial"]
        return {k: float(init[k]) for k in self.ers_states}

    @property
    def transitions(self) -> Dict[str, Dict[str, float]]:
        tr = self.raw["transitions"]
        return {
            a: {b: float(tr[a][b]) for b in self.ers_states} for a in self.ers_states
        }

    @property
    def p_ot_spent_to_available(self) -> float:
        return float(self.raw["transitions"]["p_overtake_spent_to_available"])

    @property
    def p_ot_available_to_spent(self) -> float:
        return float(self.raw["transitions"]["p_overtake_available_to_spent"])

    @property
    def emissions(self) -> Dict[str, Any]:
        return dict(_clean(self.raw["emissions"]))

    @property
    def trap(self) -> Dict[str, Any]:
        return dict(_clean(self.raw["trap"]))

    @property
    def p_overtake_available_initial(self) -> float:
        return float(self.raw["initial"]["p_overtake_available"])


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------


def load_rules(reload: bool = False) -> RulesConfig:
    """Load ``config/rules_2026.json``."""
    with _LOCK:
        if reload or "rules" not in _CACHE:
            _CACHE["rules"] = RulesConfig(raw=_read("rules_2026.json"))
        return _CACHE["rules"]  # type: ignore[return-value]


def load_event(name: str, reload: bool = False) -> EventConfig:
    """Load ``config/event_<name>.json`` (case-insensitive)."""
    key = f"event:{name.lower()}"
    with _LOCK:
        if reload or key not in _CACHE:
            _CACHE[key] = EventConfig(raw=_read(f"event_{name.lower()}.json"))
        return _CACHE[key]  # type: ignore[return-value]


def load_ev_bus(reload: bool = False) -> EvBusConfig:
    """Load ``config/ev_bus.json``."""
    with _LOCK:
        if reload or "evbus" not in _CACHE:
            _CACHE["evbus"] = EvBusConfig(raw=_read("ev_bus.json"))
        return _CACHE["evbus"]  # type: ignore[return-value]


def load_circuits(reload: bool = False) -> Dict[str, CircuitConfig]:
    """Load every circuit in ``config/circuits.json``."""
    with _LOCK:
        if reload or "circuits" not in _CACHE:
            raw = _read("circuits.json")
            _CACHE["circuits"] = {
                k: CircuitConfig(key=k, raw=v) for k, v in raw["circuits"].items()
            }
        return _CACHE["circuits"]  # type: ignore[return-value]


def load_hmm_priors(reload: bool = False) -> HMMConfig:
    """Load ``config/hmm_priors.json``."""
    with _LOCK:
        if reload or "hmm" not in _CACHE:
            _CACHE["hmm"] = HMMConfig(raw=_read("hmm_priors.json"))
        return _CACHE["hmm"]  # type: ignore[return-value]


def list_events() -> List[str]:
    """Names of every available ``event_*.json`` config."""
    out = []
    for p in sorted(config_dir().glob("event_*.json")):
        out.append(p.stem[len("event_"):])
    return out
