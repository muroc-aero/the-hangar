"""Typed error taxonomy for hangar-omd.

All user-facing failures should raise one of these so the CLI can render a
friendly, actionable message instead of a raw stack trace. Internal
assertion failures still use ``AssertionError``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationFinding:
    """One finding emitted by schema or semantic validation.

    Mirrors the shape already used by ``plan_schema.load_and_validate`` so
    existing callers can iterate findings the same way.
    """

    path: str
    message: str
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = {"path": self.path, "message": self.message}
        if self.suggestions:
            out["suggestions"] = list(self.suggestions)
        return out


class OmdError(Exception):
    """Base class for hangar-omd user-facing errors."""


class PlanValidationError(OmdError):
    """Plan failed schema or semantic validation. Carries all findings."""

    def __init__(self, findings: list[ValidationFinding]):
        self.findings = list(findings)
        summary = f"{len(findings)} validation " + (
            "error" if len(findings) == 1 else "errors"
        )
        super().__init__(summary)


class UnknownVariableError(OmdError):
    """A DV/constraint/objective short name could not be resolved to a path."""

    def __init__(self, name: str, where: str, suggestions: list[str] | None = None):
        self.name = name
        self.where = where
        self.suggestions = list(suggestions or [])
        msg = f"Unknown variable '{name}' in {where}"
        if self.suggestions:
            msg += f" (did you mean: {', '.join(self.suggestions)}?)"
        super().__init__(msg)


__all__ = [
    "ValidationFinding",
    "OmdError",
    "PlanValidationError",
    "UnknownVariableError",
]
