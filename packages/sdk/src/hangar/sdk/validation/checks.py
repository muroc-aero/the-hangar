"""Physics validation framework — findings model and generic checks.

These checks are intentionally self-contained — they depend only on Python stdlib
and basic data structures, not on any SDK infrastructure like the provenance DB
or session manager. This makes them extractable to the range-safety repo later.

Migrated from: OpenAeroStruct/oas_mcp/core/validation.py (generic parts)
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ValidationFinding:
    check_id: str
    category: str  # physics | numerics | constraints | stability
    severity: str  # error | warning | info
    confidence: str  # high | medium | low
    passed: bool
    message: str
    remediation: str = ""

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "passed": self.passed,
            "message": self.message,
            "remediation": self.remediation,
        }


def findings_to_dict(findings: list[ValidationFinding]) -> dict:
    """Aggregate findings into a block suitable for the response envelope."""
    errors = [f for f in findings if not f.passed and f.severity == "error"]
    warnings = [f for f in findings if not f.passed and f.severity == "warning"]
    infos = [f for f in findings if not f.passed and f.severity == "info"]
    return {
        "passed": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "info_count": len(infos),
        "findings": [f.to_dict() for f in findings if not f.passed],
        "all_findings": [f.to_dict() for f in findings],
    }


# The OAS-specific aero checks (check_cd_positive, check_cl_reasonable,
# check_ld_reasonable, check_cd_not_too_large) that used to live here were
# removed: hangar.oas.validation carries its own copies, and nothing else
# imported the SDK ones. The SDK keeps only the tool-agnostic findings model.
