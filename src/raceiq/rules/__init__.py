"""Rule layer: the FIA 2026 compliance ledger.

Every candidate plan passes through here before it reaches the decision engine.
An illegal plan is rejected outright rather than merely penalised - the Overtake
EV engine treats it as ``-inf``. All limits are read from
``config/rules_2026.json``; no FIA constant is hard-coded anywhere in RaceIQ.
"""

from raceiq.rules.ledger import (
    RULE_LABELS,
    ComplianceLedger,
    certificate_text,
)

__all__ = ["ComplianceLedger", "RULE_LABELS", "certificate_text"]
