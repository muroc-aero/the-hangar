"""JSON Schema for analysis plan YAML files.

Defines the canonical plan structure and provides validation functions.
The schema covers the subset needed for OAS AerostructPoint analysis
and optimization, extensible to other component types.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

# ---------------------------------------------------------------------------
# Plan JSON Schema
# ---------------------------------------------------------------------------

PLAN_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "MDAO Analysis Plan",
    "type": "object",
    "required": ["metadata", "components"],
    "additionalProperties": False,
    "properties": {
        "metadata": {
            "type": "object",
            "required": ["id", "name", "version"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "version": {"type": "integer", "minimum": 1},
                "description": {"type": "string"},
                "content_hash": {"type": "string"},
                "parent_version": {"type": "integer", "minimum": 1},
            },
        },
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "text"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "text": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "performance",
                            "structural",
                            "stability",
                            "constraint",
                            "objective",
                        ],
                    },
                    "traces_to": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["primary", "secondary", "goal"],
                    },
                    "source": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "draft",
                            "open",
                            "verified",
                            "violated",
                            "waived",
                        ],
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["metric"],
                            "additionalProperties": False,
                            "properties": {
                                "metric": {"type": "string", "minLength": 1},
                                "comparator": {
                                    "type": "string",
                                    "enum": [
                                        "<",
                                        "<=",
                                        ">",
                                        ">=",
                                        "==",
                                        "!=",
                                        "in",
                                    ],
                                },
                                "threshold": {"type": "number"},
                                "range": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 2,
                                    "maxItems": 2,
                                },
                                "units": {"type": "string"},
                            },
                        },
                    },
                    "verification": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "method": {
                                "type": "string",
                                "enum": [
                                    "automated",
                                    "visual",
                                    "comparison",
                                ],
                            },
                            "assertion": {"type": "string"},
                        },
                    },
                },
            },
        },
        "operating_points": {
            "oneOf": [
                # Single-point: flat dict of flight conditions.
                # Values can be bare numbers/strings/arrays, or an object
                # with "value" and optional "units" for explicit unit tagging.
                {
                    "type": "object",
                    "additionalProperties": {
                        "oneOf": [
                            {"type": "number"},
                            {"type": "string"},
                            {
                                "type": "array",
                                "items": {"type": "number"},
                            },
                            {
                                "type": "object",
                                "required": ["value"],
                                "additionalProperties": False,
                                "properties": {
                                    "value": {
                                        "oneOf": [
                                            {"type": "number"},
                                            {"type": "array", "items": {"type": "number"}},
                                        ],
                                    },
                                    "units": {"type": "string"},
                                },
                            },
                        ],
                    },
                },
                # Multipoint: {flight_points: [...], shared: {...}}
                {
                    "type": "object",
                    "required": ["flight_points"],
                    "additionalProperties": False,
                    "properties": {
                        "flight_points": {
                            "type": "array",
                            "minItems": 2,
                            "items": {
                                "type": "object",
                                "additionalProperties": {
                                    "oneOf": [
                                        {"type": "number"},
                                        {"type": "string"},
                                        {
                                            "type": "array",
                                            "items": {"type": "number"},
                                        },
                                        {
                                            "type": "object",
                                            "required": ["value"],
                                            "additionalProperties": False,
                                            "properties": {
                                                "value": {
                                                    "oneOf": [
                                                        {"type": "number"},
                                                        {"type": "array", "items": {"type": "number"}},
                                                    ],
                                                },
                                                "units": {"type": "string"},
                                            },
                                        },
                                    ],
                                },
                            },
                        },
                        "shared": {
                            "type": "object",
                            "additionalProperties": {
                                "oneOf": [
                                    {"type": "number"},
                                    {"type": "string"},
                                    {
                                        "type": "array",
                                        "items": {"type": "number"},
                                    },
                                    {
                                        "type": "object",
                                        "required": ["value"],
                                        "additionalProperties": False,
                                        "properties": {
                                            "value": {
                                                "oneOf": [
                                                    {"type": "number"},
                                                    {"type": "array", "items": {"type": "number"}},
                                                ],
                                            },
                                            "units": {"type": "string"},
                                        },
                                    },
                                ],
                            },
                        },
                    },
                },
            ],
        },
        "components": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "type", "config"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "type": {"type": "string", "minLength": 1},
                    "source": {"type": "string"},
                    "config": {
                        "type": "object",
                        "properties": {
                            "slots": {
                                "type": "object",
                                "additionalProperties": {
                                    "type": "object",
                                    "required": ["provider"],
                                    "properties": {
                                        "provider": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "config": {"type": "object"},
                                    },
                                    "additionalProperties": False,
                                },
                            },
                        },
                    },
                },
            },
        },
        "connections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["src", "tgt"],
                "additionalProperties": False,
                "properties": {
                    "src": {"type": "string"},
                    "tgt": {"type": "string"},
                },
            },
        },
        "shared_vars": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "consumers"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "value": {
                        "oneOf": [
                            {"type": "number"},
                            {
                                "type": "array",
                                "items": {"type": "number"},
                            },
                        ],
                    },
                    "units": {"type": "string"},
                    "consumers": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                    },
                    "rationale": {"type": "string"},
                },
            },
        },
        "composition_policy": {
            "type": "string",
            "enum": ["explicit", "auto"],
        },
        "no_auto_share": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "solvers": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "nonlinear": {
                    "type": "object",
                    "required": ["type"],
                    "additionalProperties": False,
                    "properties": {
                        "type": {"type": "string"},
                        "options": {"type": "object"},
                    },
                },
                "linear": {
                    "type": "object",
                    "required": ["type"],
                    "additionalProperties": False,
                    "properties": {
                        "type": {"type": "string"},
                        "options": {"type": "object"},
                    },
                },
            },
        },
        "design_variables": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "lower": {"type": "number"},
                    "upper": {"type": "number"},
                    "units": {"type": "string"},
                    "scaler": {"type": "number"},
                    "ref": {"type": "number"},
                    "ref0": {"type": "number"},
                    "initial": {
                        "oneOf": [
                            {"type": "number"},
                            {"type": "array", "items": {"type": "number"}},
                        ],
                    },
                    "traces_to": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "initial_values": {
            "type": "array",
            "description": (
                "Plan-level starting value overrides applied after "
                "setup().  Useful for warm-starting optimizers.  DVs "
                "can also declare `initial:` inline in "
                "design_variables[]; top-level entries here work for "
                "arbitrary paths (factory inputs, mission params, "
                "etc.)."
            ),
            "items": {
                "type": "object",
                "required": ["name", "val"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "val": {
                        "oneOf": [
                            {"type": "number"},
                            {"type": "array", "items": {"type": "number"}},
                        ],
                    },
                    "units": {"type": "string"},
                },
            },
        },
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "upper": {"type": "number"},
                    "lower": {"type": "number"},
                    "equals": {"type": "number"},
                    "scaler": {"type": "number"},
                    "units": {"type": "string"},
                    "point": {"type": "integer", "minimum": 0},
                    "traces_to": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "objective": {
            "type": "object",
            "required": ["name"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "scaler": {"type": "number"},
                "units": {"type": "string"},
                "traces_to": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "optimizer": {
            "type": "object",
            "required": ["type"],
            "additionalProperties": False,
            "properties": {
                "type": {"type": "string"},
                "options": {"type": "object"},
            },
        },
        "rationale": {
            "type": "array",
            "items": {"type": "string"},
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "decision": {"type": "string"},
                    "reason": {"type": "string"},
                    "rationale": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "stage": {"type": "string"},
                    "agent": {"type": "string"},
                    "references": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "object"},
                            ],
                        },
                    },
                    "element_path": {"type": "string"},
                    "alternatives_considered": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["option"],
                            "additionalProperties": False,
                            "properties": {
                                "option": {"type": "string"},
                                "rejected_because": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "analysis_plan": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "strategy": {"type": "string"},
                "phases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id"],
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "minLength": 1},
                            "name": {"type": "string"},
                            "mode": {"type": "string"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "success_criteria": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["metric"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "metric": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "comparator": {
                                            "type": "string",
                                            "enum": [
                                                "<",
                                                "<=",
                                                ">",
                                                ">=",
                                                "==",
                                                "!=",
                                                "in",
                                            ],
                                        },
                                        "threshold": {"type": "number"},
                                        "range": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                            "minItems": 2,
                                            "maxItems": 2,
                                        },
                                        "units": {"type": "string"},
                                    },
                                },
                            },
                            "checks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["type"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": [
                                                "plot",
                                                "assertion",
                                                "range_safety",
                                                "manual",
                                            ],
                                        },
                                        "plots": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "look_for": {"type": "string"},
                                        "command": {"type": "string"},
                                        "note": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
                "replan_triggers": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Recommended enum values (soft: checker WARNs on values outside this set)
# ---------------------------------------------------------------------------

# Recommended values for decision.stage. Not enforced by the schema; the
# completeness checker (plan_review) WARNs on values outside this set.
RECOMMENDED_DECISION_STAGES: tuple[str, ...] = (
    "problem_definition",
    "component_selection",
    "mesh_selection",
    "solver_selection",
    "dv_setup",
    "constraint_setup",
    "objective_selection",
    "operating_point_selection",
    "optimizer_selection",
    "diagnosis",
    "replan",
    "formulation",
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _build_partial_schema() -> dict[str, Any]:
    """Derive a relaxed schema that permits missing top-level sections.

    Used by the interactive plan builder to validate in-progress plans
    before every write. Nested ``required`` constraints (metadata fields,
    component fields, etc.) are preserved so a section that *is* present
    must still be structurally valid.
    """
    partial = copy.deepcopy(PLAN_SCHEMA)
    partial["required"] = []
    partial["title"] = "MDAO Analysis Plan (partial)"
    return partial


PLAN_SCHEMA_PARTIAL: dict[str, Any] = _build_partial_schema()


def validate_plan(plan: dict) -> list[dict[str, str]]:
    """Validate a plan dict against the JSON Schema.

    Args:
        plan: Parsed YAML plan dictionary.

    Returns:
        List of validation error dicts, each with "path" and "message".
        Empty list means valid.
    """
    validator = jsonschema.Draft202012Validator(PLAN_SCHEMA)
    errors = []
    for error in sorted(validator.iter_errors(plan), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append({"path": path, "message": error.message})
    return errors


def validate_partial(plan: dict) -> list[dict[str, str]]:
    """Validate a partial plan dict against the relaxed JSON Schema.

    Like :func:`validate_plan` but never complains about missing
    top-level sections. Still enforces the structural shape of every
    present section. Intended for in-progress plan authoring.
    """
    validator = jsonschema.Draft202012Validator(PLAN_SCHEMA_PARTIAL)
    errors = []
    for error in sorted(validator.iter_errors(plan), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append({"path": path, "message": error.message})
    return errors


def load_and_validate(path: Path) -> tuple[dict, list[dict[str, str]]]:
    """Load a YAML file and validate it against the plan schema.

    Args:
        path: Path to plan YAML file.

    Returns:
        Tuple of (plan_dict, errors). The plan dict is the raw parsed
        YAML. Errors list is empty if valid.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        yaml.YAMLError: If the file is not valid YAML.
    """
    with open(path) as f:
        plan = yaml.safe_load(f)

    if not isinstance(plan, dict):
        return {}, [{"path": "(root)", "message": "Plan must be a YAML mapping"}]

    errors = validate_plan(plan)
    return plan, errors
