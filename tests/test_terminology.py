"""Phase 2 test: 2026 terminology compliance (legacy DRS concept ban).

The 2026 F1 rules replaced the DRS concept with Active Aero + Overtake Mode.
This scans source, frontend, config, data JSON and documentation for legacy
terminology and fails on any *operational* reference.

The only permitted mentions are documentary provenance:
  * ``drs_deleted`` in ``config/rules_2026.json`` (the explicit declaration
    that the concept is de-listed), and
  * prose that states the concept was *replaced* (historical context such as
    "Overtake Mode (replaces DRS)" in the design spec).

Bare lowercase ``drs`` is tolerated in that one documentary window; every
operational phrase (``drs zone`` / ``drs available`` / ``drs enabled`` /
``drs activation`` / ``drs deployment``) is forbidden regardless of case.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Bare uppercase token: the legacy mechanism name. Case-sensitive on purpose,
# so the config key ``drs_deleted`` (a declaration of removal) is not a hit.
_BARE_DRS = re.compile(r"\bDRS\b")

# Operational phrases are forbidden in any case / hyphenation. Filler verbs
# ("DRS is available", "DRS becomes enabled") are caught too.
_OPERATIONAL = re.compile(
    r"\bdrs[\s-]*(?:(?:is|was|becomes|becoming|being)[\s-]*)?"
    r"(zone|available|enabled|activation|deployment|use|usage|wing|mode)\b",
    re.IGNORECASE,
)

# Documentary mentions allowed: they only exist to state the concept is gone.
_ALLOW_BARE = (
    "replaces DRS",
    "replaced DRS",
    "replacing DRS",
    "(replaces DRS",
    "pre-2026",
)

SCAN_ROOTS = (
    ("src", ("*.py",)),
    ("scripts", ("*.py",)),
    ("frontend", ("*.html",)),
    ("frontend/src", ("*.ts", "*.tsx", "*.css")),
    ("config", ("*.json",)),
    ("data", ("*.json",)),
    ("frontend/public/data", ("*.json",)),
    (".", ("*.md",)),
    ("docs", ("*.md",)),
)


def _candidate_files():
    seen = set()
    for sub, glbs in SCAN_ROOTS:
        base = ROOT / sub
        if not base.is_dir():
            continue
        for glb in glbs:
            for p in sorted(base.glob(glb)):
                rp = str(p.resolve())
                if rp in seen:
                    continue
                if any(
                    skip in rp
                    for skip in ("node_modules", "__pycache__", "dist", ".git")
                ):
                    continue
                seen.add(rp)
                yield p


def test_no_operational_drs_terminology():
    hits = []
    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _OPERATIONAL.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:120]}")
                continue
            if not _BARE_DRS.search(line):
                continue
            if "drs_deleted" in line:
                continue
            if any(a in line for a in _ALLOW_BARE):
                continue
            hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:120]}")
    assert not hits, "Legacy DRS terminology found:\n" + "\n".join(hits)