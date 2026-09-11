"""Inference layer: estimating what nobody publishes.

No model here is trained. SoC comes from a deterministic physics observer, ERS
mode and clipping from rule-based detectors on public channels, and the rival's
hidden state from an analytically-initialised 8-state HMM.
"""

from raceiq.inference.clipping import ClippingDetector, clipping_flags
from raceiq.inference.ers_mode import ErsClassifier
from raceiq.inference.opponent_belief import OpponentBelief
from raceiq.inference.soc_observer import SocObserver, observe_field

__all__ = [
    "ClippingDetector", "clipping_flags",
    "ErsClassifier",
    "OpponentBelief",
    "SocObserver", "observe_field",
]
