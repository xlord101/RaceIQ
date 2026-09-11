"""Pass-probability model for the Overtake EV engine.

This is the **only** trained model in RaceIQ (spec section 5). Everything else
is deterministic physics, rule logic, dynamic programming, or an HMM with an
*analytic* prior. Per the master instructions we use ``sklearn``
:class:`~sklearn.linear_model.LogisticRegression` (interpretable, calibrated
probabilities) wrapped in :class:`~sklearn.calibration.CalibratedClassifierCV`
with :class:`~sklearn.model_selection.GroupKFold` grouping by race/circuit so a
pass at one circuit cannot leak into the held-out estimate of another.

Until the model is fitted it falls back to a transparent analytic heuristic
(the "Simulation-mode pre-training" fallback described in the spec) so the EV
engine is usable end-to-end before real OpenF1 labels exist. The heuristic is
deliberately simple and monotonic in the same features the LR uses.

Prior art: arXiv:2603.01290 (cited, framing adopted, implementation original).
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

try:  # sklearn is a hard dependency of this module only.
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold, cross_val_predict
    _HAVE_SKLEARN = True
except Exception:  # pragma: no cover - defensive
    _HAVE_SKLEARN = False


#: The 12 features the spec mandates for ``P(pass)``, in fixed order.
FEATURE_NAMES: List[str] = [
    "gap_ahead_s",
    "closing_speed_kph",
    "straight_remaining_m",
    "tyre_age_delta_laps",
    "own_est_soc",
    "rival_est_soc",
    "rival_P_Lderate",
    "rival_P_Lharvest",
    "trap_flag",
    "overtake_mode_active",
    "circuit_harvest_potential_mj",
    "laps_remaining",
]


def _as_feature_row(features: Dict[str, float]) -> np.ndarray:
    """Project a feature mapping onto the fixed 12-feature vector order."""
    row = np.zeros((1, len(FEATURE_NAMES)), dtype=float)
    for i, name in enumerate(FEATURE_NAMES):
        row[0, i] = float(features.get(name, 0.0))
    return row


class PassModel:
    """Calibrated logistic-regression estimate of ``P(pass)``.

    Parameters
    ----------
    feature_names:
        The ordered feature list. Defaults to the 12 spec features.
    """

    def __init__(self, feature_names: Optional[Sequence[str]] = None) -> None:
        self.feature_names: List[str] = list(feature_names or FEATURE_NAMES)
        self._fitted = False
        self._model = None
        self._base = None
        self._isotonic = None
        self._use_isotonic = False
        self.classes_: Optional[np.ndarray] = None
        self.n_fit_samples: int = 0

    # ------------------------------------------------------------------
    @property
    def trained(self) -> bool:
        """Whether :meth:`fit` has been called successfully."""
        return self._fitted

    def fit(
        self,
        X: Iterable[Sequence[float]],
        y: Sequence[int],
        groups: Optional[Sequence[object]] = None,
    ) -> "PassModel":
        """Fit the calibrated logistic regressor.

        ``X`` is an iterable of feature vectors (list/ndarray) aligned with
        :attr:`feature_names`; ``y`` are binary pass labels (1 = passed);
        ``groups`` (race id / circuit) drive the GroupKFold cross-fitting.
        """
        if not _HAVE_SKLEARN:  # pragma: no cover - defensive
            raise RuntimeError("sklearn is required to fit PassModel")

        Xa = np.asarray(list(X), dtype=float)
        ya = np.asarray(list(y), dtype=int)
        if Xa.ndim != 2 or Xa.shape[1] != len(self.feature_names):
            raise ValueError(
                f"X must have shape (n, {len(self.feature_names)}); got {Xa.shape}"
            )
        if Xa.shape[0] != ya.shape[0]:
            raise ValueError("X and y length mismatch")

        base = LogisticRegression(
            max_iter=1000, class_weight="balanced", C=1.0, solver="lbfgs"
        )
        # sklearn's CalibratedClassifierCV does NOT forward `groups` to its
        # internal splitter, so a GroupKFold inside it cannot honour grouping.
        # We reproduce the spec's intent (isotonic calibration, GroupKFold by
        # race/circuit) explicitly with cross_val_predict + IsotonicRegression
        # for the grouped path, and use CalibratedClassifierCV otherwise.
        if groups is not None and len(set(groups)) >= 3:
            oof = cross_val_predict(
                base,
                Xa,
                ya,
                cv=GroupKFold(n_splits=3),
                groups=np.asarray(list(groups)),
                method="predict_proba",
            )[:, 1]
            self._isotonic = IsotonicRegression(
                out_of_bounds="clip", y_min=0.0, y_max=1.0
            )
            self._isotonic.fit(oof, ya)
            base.fit(Xa, ya)
            self._base = base
            self._use_isotonic = True
        else:
            self._model = CalibratedClassifierCV(base, method="isotonic", cv=3)
            self._model.fit(Xa, ya)
            self._use_isotonic = False
        self.classes_ = np.array([0, 1])
        self.n_fit_samples = int(Xa.shape[0])
        self._fitted = True
        return self

    # ------------------------------------------------------------------
    def predict_proba(
        self,
        features: Dict[str, float],
        *,
        warn_if_untrained: bool = False,
    ) -> float:
        """Return ``P(pass)`` in ``[0, 1]`` for one overtaking scenario.

        If the model has not been fitted it returns the analytic heuristic
        (transparent, monotonic in the same features) rather than raising, so
        the EV engine is usable before real labels exist.
        """
        row = _as_feature_row(features)
        if self._fitted:
            if self._use_isotonic and self._base is not None and self._isotonic is not None:
                p_raw = self._base.predict_proba(row)[0, 1]
                proba = float(self._isotonic.predict(np.array([p_raw]))[0])
            elif self._model is not None:
                proba = float(self._model.predict_proba(row)[0, 1])
            else:  # pragma: no cover - defensive
                proba = self.heuristic_p_pass(features)
            return min(max(proba, 0.0), 1.0)
        return self.heuristic_p_pass(features)

    # ------------------------------------------------------------------
    @staticmethod
    def heuristic_p_pass(features: Dict[str, float]) -> float:
        """Transparent pre-training estimate of ``P(pass)``.

        A small linear score in the same 12 features, squashed through a
        logistic, so the sign of every effect is obvious and defensible:

        * smaller gap to the car ahead -> easier to pass,
        * higher closing speed / longer straight remaining -> easier,
        * rival ``Lderate`` (genuinely empty) -> much easier,
        * rival ``Lharvest`` (trap) / ``trap_flag`` -> harder,
        * low own SoC -> cannot deploy, harder.
        """
        gap = float(features.get("gap_ahead_s", 1.0))
        close = float(features.get("closing_speed_kph", 0.0))
        straight = float(features.get("straight_remaining_m", 0.0))
        own_soc = float(features.get("own_est_soc", 2.0))
        p_ld = float(features.get("rival_P_Lderate", 0.0))
        p_lh = float(features.get("rival_P_Lharvest", 0.0))
        trap = float(features.get("trap_flag", 0.0))
        ot_active = float(features.get("overtake_mode_active", 0.0))

        # Logistic score: +easy / -hard. Calibrated so a 0.5 s gap, 10 kph
        # closing, 300 m straight, empty rival sits around 0.8.
        #
        # The intercept is negative on purpose: the remaining terms already sum
        # to ~+2.9 in that reference case, so a positive intercept would push
        # every plausible scenario above 0.9 and make the EV engine say GO
        # almost unconditionally (only the trap override would ever say HOLD).
        score = (
            -1.5
            - 1.6 * gap
            + 0.020 * close
            + 0.0020 * straight
            + 0.45 * own_soc
            + 2.0 * p_ld
            - 1.6 * p_lh
            - 1.8 * trap
            + 0.6 * ot_active
        )
        p = 1.0 / (1.0 + np.exp(-score))
        return min(max(float(p), 0.0), 1.0)


__all__ = ["PassModel", "FEATURE_NAMES"]
