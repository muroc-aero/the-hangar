"""JSON Schema for analysis plan YAML files.

Defines the canonical plan structure and provides validation functions.
The schema covers the subset needed for OAS AerostructPoint analysis
and optimization, extensible to other component types.
"""

from __future__ import annotations

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
                },
            },
        },
        "operating_points": {
            "type": "object",
            "additionalProperties": {
                "oneOf": [
                    {"type": "number"},
                    {"type": "string"},
                    {
                        "type": "array",
                        "items": {"type": "number"},
                    },
                ],
            },
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
                    "config": {"type": "object"},
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
                    "decision": {"type": "string"},
                    "reason": {"type": "string"},
                    "timestamp": {"type": "string"},
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


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
