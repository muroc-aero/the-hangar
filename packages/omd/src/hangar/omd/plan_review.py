"""Plan completeness checker.

``omd-cli plan review`` uses this module to surface the gap between
"valid plan" and "well-documented plan". It loads an assembled plan
and emits a list of :class:`ReviewFinding` records covering:

  - missing or under-specified requirements (no acceptance_criteria
    or verification method)
  - decisions missing ``element_path`` (so the plan knowledge graph
    cannot render a ``justifies`` edge against a concrete target)
  - configurable sections (mesh, DVs, constraints, objective, solver,
    optimizer) with no decisions pointing at them
  - missing ``analysis_plan`` section or phases without
    ``success_criteria`` / ``checks``
  - missing top-level ``rationale``
  - graph-completeness warnings mirroring the rules used by the plan
    graph builder, so the viewer and the checker stay in sync.

Exit code is always 0. Structured JSON output via ``--format json`` lets
downstream callers gate CI on specific findings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from hangar.omd.plan_paths import resolve_element_path
from hangar.omd.plan_schema import (
    RECOMMENDED_DECISION_STAGES,
    load_and_validate,
    validate_plan,
)


Severity = Literal["OK", "WARN", "MISSING", "ERROR"]


@dataclass
class ReviewFinding:
    """A single completeness finding.

    Attributes:
        section: Top-level plan section the finding applies to.
        severity: OK | WARN | MISSING | ERROR.
        message: Short human-readable description.
        hint: Optional actionable suggestion.
    """

    section: str
    severity: Severity
    message: str
    hint: str = ""


_SECTIONS = (
    "metadata",
    "requirements",
    "decisions",
    "components",
    "operating_points",
    "solvers",
    "design_variables",
    "constraints",
    "objective",
    "optimizer",
    "analysis_plan",
    "rationale",
    "graph",
)


def review_plan(plan: dict) -> list[ReviewFinding]:
    """Return the list of completeness findings for a plan dict."""
    findings: list[ReviewFinding] = []

    schema_errors = validate_plan(plan)
    for err in schema_errors:
        findings.append(ReviewFinding(
            section="schema",
            severity="ERROR",
            message=f"{err['path']}: {err['message']}",
            hint="Fix schema errors before reviewing completeness.",
        ))
    if schema_errors:
        return findings

    _check_requirements(plan, findings)
    _check_decisions(plan, findings)
    _check_analysis_plan(plan, findings)
    _check_rationale(plan, findings)
    return findings


# ---------------------------------------------------------------------------
# Section checks
# ---------------------------------------------------------------------------


def _check_requirements(plan: dict, findings: list[ReviewFinding]) -> None:
    requirements = plan.get("requirements") or []
    if not requirements:
        findings.append(ReviewFinding(
            section="requirements",
            severity="MISSING",
            message="No requirements declared.",
            hint="Add a requirements.yaml (or inline block) with at least one id/text entry.",
        ))
        return

    without_ac = [r.get("id", "?") for r in requirements
                  if not r.get("acceptance_criteria")]
    if without_ac:
        findings.append(ReviewFinding(
            section="requirements",
            severity="WARN",
            message=(
                f"{len(without_ac)}/{len(requirements)} requirements "
                f"lack acceptance_criteria: {', '.join(without_ac)}"
            ),
            hint="Add acceptance_criteria so runs can be checked automatically.",
        ))

    without_ver = [r.get("id", "?") for r in requirements
                   if not r.get("verification")]
    if without_ver:
        findings.append(ReviewFinding(
            section="requirements",
            severity="WARN",
            message=(
                f"{len(without_ver)}/{len(requirements)} requirements "
                f"lack a verification method: {', '.join(without_ver)}"
            ),
            hint="Add verification.method (automated | visual | comparison).",
        ))


def _check_decisions(plan: dict, findings: list[ReviewFinding]) -> None:
    decisions = plan.get("decisions") or []
    if not decisions:
        findings.append(ReviewFinding(
            section="decisions",
            severity="WARN",
            message="No decisions recorded.",
            hint="Document why key choices were made (stage + rationale + element_path).",
        ))
    else:
        # Stage values outside the recommended set
        unusual_stages: set[str] = set()
        for dec in decisions:
            stage = (dec or {}).get("stage")
            if stage and stage not in RECOMMENDED_DECISION_STAGES:
                unusual_stages.add(stage)
        if unusual_stages:
            findings.append(ReviewFinding(
                section="decisions",
                severity="WARN",
                message=(
                    f"Decisions use stage values outside the recommended set: "
                    f"{', '.join(sorted(unusual_stages))}"
                ),
                hint="See RECOMMENDED_DECISION_STAGES in plan_schema.py.",
            ))

        # Decisions without element_path cannot render as justifies edges
        missing_ep = [d.get("id", "?") for d in decisions
                      if not d.get("element_path")]
        if missing_ep:
            findings.append(ReviewFinding(
                section="graph",
                severity="WARN",
                message=(
                    f"{len(missing_ep)}/{len(decisions)} decisions lack "
                    f"element_path: {', '.join(missing_ep)}"
                ),
                hint="Graph cannot render justifies edges for these decisions.",
            ))

        # Decisions with element_path that fails to resolve
        unresolved: list[str] = []
        for dec in decisions:
            path = dec.get("element_path")
            if path and resolve_element_path(plan, path) is None:
                unresolved.append(f"{dec.get('id', '?')} ({path})")
        if unresolved:
            findings.append(ReviewFinding(
                section="graph",
                severity="WARN",
                message=(
                    f"{len(unresolved)} decisions have unresolvable "
                    f"element_path: {', '.join(unresolved)}"
                ),
                hint="Check section/id names; update element_path or rename elements.",
            ))

    # Configurable sections with no decisions pointing at them
    coverage = _decision_coverage(plan, decisions)
    uncovered = [s for s, covered in coverage.items() if not covered]
    if uncovered:
        findings.append(ReviewFinding(
            section="decisions",
            severity="WARN",
            message=(
                f"Configurable sections with no decisions: "
                f"{', '.join(uncovered)}"
            ),
            hint="Add decisions explaining why each configurable section was set this way.",
        ))


def _check_analysis_plan(plan: dict, findings: list[ReviewFinding]) -> None:
    ap = plan.get("analysis_plan")
    if not isinstance(ap, dict):
        findings.append(ReviewFinding(
            section="analysis_plan",
            severity="MISSING",
            message="No analysis_plan section.",
            hint="Document process: strategy, phases, success_criteria, checks.",
        ))
        return

    phases = ap.get("phases") or []
    if not phases:
        findings.append(ReviewFinding(
            section="analysis_plan",
            severity="WARN",
            message="analysis_plan has no phases.",
            hint="Add at least one phase describing how the analysis should proceed.",
        ))
        return

    phase_ids = {p.get("id") for p in phases if isinstance(p, dict)}
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        pid = phase.get("id", "?")
        if not phase.get("success_criteria"):
            findings.append(ReviewFinding(
                section="analysis_plan",
                severity="WARN",
                message=f"phase {pid!r} has no success_criteria.",
                hint="Define success_criteria so run results can be checked against intent.",
            ))
        if not phase.get("checks"):
            findings.append(ReviewFinding(
                section="analysis_plan",
                severity="WARN",
                message=f"phase {pid!r} has no checks.",
                hint="Add checks (plot review, assertions, range_safety).",
            ))
        for dep in phase.get("depends_on") or []:
            if dep not in phase_ids:
                findings.append(ReviewFinding(
                    section="analysis_plan",
                    severity="ERROR",
                    message=f"phase {pid!r} depends_on unknown phase {dep!r}.",
                    hint="Check phase ids in depends_on match declared phases.",
                ))


def _check_rationale(plan: dict, findings: list[ReviewFinding]) -> None:
    if not plan.get("rationale"):
        findings.append(ReviewFinding(
            section="rationale",
            severity="MISSING",
            message="No top-level rationale.",
            hint="Add a short rationale describing the purpose of this plan.",
        ))


# ---------------------------------------------------------------------------
# Decision coverage helper
# ---------------------------------------------------------------------------


def _decision_coverage(plan: dict, decisions: list[dict]) -> dict[str, bool]:
    """Per-section flag: does any decision point at this section?

    Used to flag configurable sections with no documented rationale.
    """
    sections_present: dict[str, bool] = {}
    if any(_surface_has_mesh(surf) for surf in _iter_surfaces(plan)):
        sections_present["mesh"] = False
    if plan.get("design_variables"):
        sections_present["design_variables"] = False
    if plan.get("constraints"):
        sections_present["constraints"] = False
    if plan.get("objective"):
        sections_present["objective"] = False
    if plan.get("solvers"):
        sections_present["solvers"] = False
    if plan.get("optimizer"):
        sections_present["optimizer"] = False

    for dec in decisions or []:
        path = (dec or {}).get("element_path") or ""
        stage = (dec or {}).get("stage") or ""
        combined = f"{path} {stage}"
        for section in list(sections_present):
            if _section_matches(section, combined):
                sections_present[section] = True
    return sections_present


def _section_matches(section: str, text: str) -> bool:
    text = text.lower()
    if section == "mesh":
        return any(token in text for token in ("mesh", "num_y", "num_x"))
    if section == "design_variables":
        return "design_variables" in text or "dv_setup" in text or "dv_" in text
    if section == "constraints":
        return "constraint" in text
    if section == "objective":
        return "objective" in text
    if section == "solvers":
        return "solver" in text
    if section == "optimizer":
        return "optimizer" in text
    return False


def _iter_surfaces(plan: dict):
    for comp in plan.get("components") or []:
        surfaces = (comp or {}).get("config", {}).get("surfaces") or []
        for surf in surfaces:
            yield surf


def _surface_has_mesh(surf: dict) -> bool:
    return bool(surf) and ("num_y" in surf or "num_x" in surf)


# ---------------------------------------------------------------------------
# Loading and formatting
# ---------------------------------------------------------------------------


_SEVERITY_RANK = {"OK": 0, "MISSING": 1, "WARN": 2, "ERROR": 3}


def review_plan_file(path: Path) -> tuple[dict, list[ReviewFinding]]:
    """Load a plan (assembled YAML or plan directory) and review it.

    If ``path`` is a directory, look for a ``plan.yaml`` inside; if
    absent, assemble it from modular files on the fly (via
    :func:`assemble.assemble_plan`).
    """
    path = Path(path)
    if path.is_dir():
        assembled = path / "plan.yaml"
        if assembled.exists():
            plan, errs = load_and_validate(assembled)
            if errs:
                return plan, [
                    ReviewFinding("schema", "ERROR", f"{e['path']}: {e['message']}")
                    for e in errs
                ]
            return plan, review_plan(plan)
        # Fallback: assemble in memory
        from hangar.omd.assemble import _merge_yaml_files  # noqa: PLC0415
        plan = _merge_yaml_files(path)
        return plan, review_plan(plan)

    plan, errs = load_and_validate(path)
    if errs:
        return plan, [
            ReviewFinding("schema", "ERROR", f"{e['path']}: {e['message']}")
            for e in errs
        ]
    return plan, review_plan(plan)


def format_findings_text(plan: dict, findings: list[ReviewFinding]) -> str:
    """Render findings as a terminal-friendly summary block."""
    meta = plan.get("metadata") or {}
    pid = meta.get("id", "(unknown)")
    ver = meta.get("version", "?")

    lines = [
        f"Plan: {pid} (v{ver})",
        "\u2501" * 60,
    ]

    by_section: dict[str, list[ReviewFinding]] = {}
    for f in findings:
        by_section.setdefault(f.section, []).append(f)

    for section in _SECTIONS:
        entries = by_section.get(section)
        if entries is None:
            if section in plan or section == "metadata":
                lines.append(f"{section:<17} OK")
            continue
        top = max(entries, key=lambda f: _SEVERITY_RANK[f.severity])
        marker = {
            "OK": "OK",
            "MISSING": "MISSING",
            "WARN": "WARN",
            "ERROR": "ERROR",
        }[top.severity]
        lines.append(f"{section:<17} {marker}  {top.message}")
        for f in entries[1:]:
            lines.append(f"{' ' * 21}... {f.severity}  {f.message}")

    # Any findings in sections not in _SECTIONS
    extra = [s for s in by_section if s not in _SECTIONS]
    for section in extra:
        for f in by_section[section]:
            lines.append(f"{section:<17} {f.severity}  {f.message}")

    total = len(findings)
    warns = sum(1 for f in findings if f.severity == "WARN")
    missing = sum(1 for f in findings if f.severity == "MISSING")
    errors = sum(1 for f in findings if f.severity == "ERROR")
    lines.append("")
    lines.append(
        f"{total} finding(s): "
        f"{errors} error, {missing} missing, {warns} warn"
    )
    return "\n".join(lines)


def format_findings_json(plan: dict, findings: list[ReviewFinding]) -> str:
    """Render findings as JSON for downstream tooling."""
    meta = plan.get("metadata") or {}
    return json.dumps(
        {
            "plan_id": meta.get("id"),
            "version": meta.get("version"),
            "findings": [asdict(f) for f in findings],
            "summary": {
                "total": len(findings),
                "error": sum(1 for f in findings if f.severity == "ERROR"),
                "missing": sum(1 for f in findings if f.severity == "MISSING"),
                "warn": sum(1 for f in findings if f.severity == "WARN"),
            },
        },
        indent=2,
    )


__all__ = [
    "ReviewFinding",
    "review_plan",
    "review_plan_file",
    "format_findings_text",
    "format_findings_json",
]
