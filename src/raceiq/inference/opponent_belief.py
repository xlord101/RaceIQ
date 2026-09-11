"""8-state opponent HMM - inferring a rival's hidden battery state.

Hidden state = ``ERS in {H, M, Lharvest, Lderate} x Overtake in {available, spent}``.

**Nothing here is trained.** There is no public ground-truth SoC/ERS label, so
Baum-Welch is unusable (and the prior-art paper reports EM is unreliable before
~Race 4). The emission parameters are set analytically from domain knowledge
(``config/hmm_priors.json``) and the belief is propagated with the classic
forward algorithm::

    alpha_t(j) = P(o_t | j) * sum_i alpha_{t-1}(i) * T_ij

The point of the HMM: "the rival looks slow" is ambiguous. It is either

* ``Lderate``  - genuinely empty, full throttle but no electrical power (**go**),
* ``Lharvest`` - deliberately saving while running low-drag aero, building a
  hidden reserve to attack you (**trap - hold**).

Prior art: arXiv:2603.01290 (cited, framing adopted, implementation original).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import numpy as np

from raceiq.config import HMMConfig, load_hmm_priors
from raceiq.types import Belief

__all__ = ["OpponentBelief", "compute_emissions", "GAUSSIAN_CHANNELS"]

#: Continuous emission channels (Gaussian per ERS bin).
GAUSSIAN_CHANNELS = ("dv_trap_kph", "delta_throttle", "delta_bbrake_m", "speed_variance")


def _norm(x: np.ndarray) -> np.ndarray:
    s = float(x.sum())
    return x / s if s > 0 else np.full_like(x, 1.0 / len(x))


class OpponentBelief:
    """Recursive Bayesian filter over the 8 hidden opponent states.

    Parameters
    ----------
    n_states:
        Always 8 for the 2026 model (4 ERS bins x 2 Overtake statuses).
    hmm:
        Analytic priors; loaded from ``config/hmm_priors.json`` by default.
    """

    def __init__(self, n_states: int = 8, hmm: Optional[HMMConfig] = None) -> None:
        if n_states != 8:
            raise ValueError("The 2026 opponent model has exactly 8 states")
        self.hmm = hmm or load_hmm_priors()
        self.n_states = 8
        self.ers = list(self.hmm.ers_states)
        self.n_ers = len(self.ers)
        self.T = self._build_transitions()
        self.belief = self._prior()
        self.emission_params = self.hmm.emissions
        self.trap_cfg = self.hmm.trap

    # ------------------------------------------------------------------
    def _build_transitions(self) -> np.ndarray:
        """Joint 8x8 transition matrix over (ERS, Overtake)."""
        t_ers = self.hmm.transitions
        A = np.array(
            [[t_ers[a][b] for b in self.ers] for a in self.ers], dtype=float
        )
        A = A / A.sum(axis=1, keepdims=True)

        p_avail_to_spent = self.hmm.p_ot_available_to_spent
        p_spent_to_avail = self.hmm.p_ot_spent_to_available
        # Overtake status: 0 = available, 1 = spent
        B = np.array(
            [
                [1.0 - p_avail_to_spent, p_avail_to_spent],
                [p_spent_to_avail, 1.0 - p_spent_to_avail],
            ],
            dtype=float,
        )

        T = np.zeros((8, 8), dtype=float)
        for i in range(self.n_ers):
            for j in range(self.n_ers):
                for a in range(2):
                    for b in range(2):
                        T[i * 2 + a, j * 2 + b] = A[i, j] * B[a, b]
        return T / T.sum(axis=1, keepdims=True)

    def _prior(self) -> np.ndarray:
        """Initial belief over the 8 states."""
        p_ers = self.hmm.initial_ers
        p_avail = self.hmm.p_overtake_available_initial
        v = np.zeros(8, dtype=float)
        for i, name in enumerate(self.ers):
            v[i * 2 + 0] = p_ers[name] * p_avail
            v[i * 2 + 1] = p_ers[name] * (1.0 - p_avail)
        return _norm(v)

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Return to the analytic prior (start of a stint / new rival)."""
        self.belief = self._prior()

    def emission_likelihood(self, emissions: Dict[str, float]) -> np.ndarray:
        """``P(observation | state)`` for all 8 states.

        Gaussian for the continuous channels, Bernoulli for the inferred
        Active Aero flag ``zaero``.
        """
        em = self.emission_params
        logp = np.zeros(self.n_states, dtype=float)

        for ch in GAUSSIAN_CHANNELS:
            if ch not in em:
                continue
            x = emissions.get(ch)
            if x is None:
                continue
            for i, name in enumerate(self.ers):
                mu = float(em[ch][name]["mean"])
                sigma = max(float(em[ch][name]["sigma"]), 1e-6)
                z = (float(x) - mu) / sigma
                lp = -0.5 * z * z - np.log(sigma * np.sqrt(2.0 * np.pi))
                logp[i * 2 + 0] += lp
                logp[i * 2 + 1] += lp

        zaero = emissions.get("zaero")
        if zaero is not None:
            p = {name: float(em["zaero"][name]) for name in self.ers}
            for i, name in enumerate(self.ers):
                pi = min(max(p[name], 1e-6), 1 - 1e-6)
                lp = np.log(pi) if zaero else np.log(1.0 - pi)
                logp[i * 2 + 0] += lp
                logp[i * 2 + 1] += lp

        m = logp.max()
        return np.exp(logp - m)

    # ------------------------------------------------------------------
    def update(self, emissions: Dict[str, float]) -> Belief:
        """Advance the belief by one observation (forward algorithm).

        Parameters
        ----------
        emissions:
            ``dv_trap_kph``, ``delta_throttle``, ``delta_bbrake_m``,
            ``speed_variance``, ``zaero`` (0/1), and optionally
            ``in_aero_zone`` (bool) for the trap test.

        Returns
        -------
        Belief
            Posterior plus the counter-harvest trap verdict.
        """
        like = self.emission_likelihood(emissions)
        predicted = self.T.T @ self.belief          # sum_i alpha_i T_ij
        posterior = _norm(predicted * like)
        self.belief = posterior

        p_ers = {
            name: float(posterior[i * 2] + posterior[i * 2 + 1])
            for i, name in enumerate(self.ers)
        }
        p_ot_available = float(
            sum(posterior[i * 2] for i in range(self.n_ers))
        )

        trap_prob, trap_flag = self._trap(p_ers, emissions)

        return Belief(
            probs=posterior.copy(),
            p_ers=p_ers,
            p_overtake_available=p_ot_available,
            trap_prob=float(trap_prob),
            trap_flag=bool(trap_flag),
            evidence={k: float(v) for k, v in emissions.items()
                      if isinstance(v, (int, float, bool, np.floating))},
        )

    def _trap(
        self, p_ers: Dict[str, float], emissions: Dict[str, float]
    ) -> tuple:
        """Counter-harvest trap test.

        Fires when the rival most likely is saving on purpose (``Lharvest``)
        rather than being empty (``Lderate``), while still running low-drag
        Active Aero - i.e. it is *building* a reserve to attack you.
        """
        cfg = self.trap_cfg
        p_h = p_ers.get("Lharvest", 0.0)
        p_d = p_ers.get("Lderate", 0.0)

        ok = p_h >= float(cfg["p_Lharvest_threshold"])
        ok = ok and p_d <= float(cfg["p_Lderate_ceiling"])
        ok = ok and (p_h - p_d) >= float(cfg["min_posterior_margin"])
        if cfg.get("require_zaero"):
            ok = ok and bool(emissions.get("zaero", 0))
        if cfg.get("require_in_aero_zone"):
            ok = ok and bool(emissions.get("in_aero_zone", True))
        return (min(1.0, max(0.0, p_h - p_d)), ok)

    # ------------------------------------------------------------------
    def batch(self, observations: Sequence[Dict[str, float]]) -> Belief:
        """Run the filter over a sequence; returns the final belief."""
        self.reset()
        b: Optional[Belief] = None
        for obs in observations:
            b = self.update(obs)
        assert b is not None
        return b


def compute_emissions(
    speed_trace: Any,
    baseline_speed_kph: Optional[float] = None,
    brake_distance_m: Optional[float] = None,
    baseline_brake_m: Optional[float] = None,
    in_aero_zone: bool = True,
) -> Dict[str, float]:
    """Derive HMM emission values from public telemetry for one rival.

    All inputs are public channels (speed, throttle, brake, distance). The
    Active Aero flag has **no** public channel, so ``zaero`` is *inferred* from
    whether the car's top speed on the straight is high relative to its own
    cornering speed - a low-drag signature.

    Returns
    -------
    dict
        ``dv_trap_kph, delta_throttle, delta_bbrake_m, speed_variance, zaero,
        in_aero_zone``
    """
    try:
        speed = np.asarray(speed_trace["Speed"], dtype=float)
        dist = np.asarray(speed_trace["Distance"], dtype=float)
        thr = np.asarray(speed_trace.get("Throttle", np.ones_like(speed)), dtype=float)
    except Exception:  # pragma: no cover - defensive
        return {
            "dv_trap_kph": 0.0, "delta_throttle": 0.0, "delta_bbrake_m": 0.0,
            "speed_variance": 10.0, "zaero": 0, "in_aero_zone": bool(in_aero_zone),
        }

    if thr.max() > 1.5:
        thr = thr / 100.0

    if len(speed) == 0:  # pragma: no cover - defensive
        return {
            "dv_trap_kph": 0.0, "delta_throttle": 0.0, "delta_bbrake_m": 0.0,
            "speed_variance": 10.0, "zaero": 0, "in_aero_zone": bool(in_aero_zone),
        }

    vmax = float(np.nanmax(speed))
    base = float(baseline_speed_kph) if baseline_speed_kph else float(np.nanmedian(speed))

    # super-clipping fraction: flat out but speed not rising
    dv = np.diff(speed, prepend=speed[0])
    flat = (thr >= 0.98) & (dv <= 0.35) & (speed >= 150.0)
    delta_throttle = float(flat.mean())

    zaero = int(vmax >= 0.95 * base and delta_throttle < 0.35) if base > 0 else 0

    bb = 0.0
    if brake_distance_m is not None and baseline_brake_m is not None:
        bb = float(brake_distance_m) - float(baseline_brake_m)

    return {
        "dv_trap_kph": float(vmax - base),
        "delta_throttle": delta_throttle,
        "delta_bbrake_m": bb,
        "speed_variance": float(np.nanvar(speed)),
        "zaero": zaero,
        "in_aero_zone": bool(in_aero_zone),
    }
