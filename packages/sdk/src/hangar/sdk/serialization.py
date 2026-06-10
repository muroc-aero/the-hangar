"""Canonical JSON serialization for numpy-bearing payloads.

Single home for the numpy-aware encoder that used to be copied into
``provenance/db.py``, ``artifacts/store.py``, and ``cli/runner.py``. The
copies drifted: only the provenance one sanitized inf/nan, so artifacts and
CLI output could emit the non-standard ``Infinity``/``NaN`` literals that
break ``JSON.parse()`` in browsers and strict parsers.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np


def sanitize_for_json(obj: Any) -> Any:
    """Replace inf/nan with JSON-safe ``None``, recursing into containers."""
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    return obj


class NumpyEncoder(json.JSONEncoder):
    """JSONEncoder that handles numpy scalars/arrays and sanitizes inf/nan."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.ndarray):
            return sanitize_for_json(obj.tolist())
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            val = float(obj)
            if math.isinf(val) or math.isnan(val):
                return None
            return val
        if isinstance(obj, np.bool_):
            return bool(obj)
        # str() fallback for any other un-serialisable object
        return str(obj)


def json_dumps(obj: Any, pretty: bool = False) -> str:
    """Serialize *obj* to JSON, handling numpy types and inf/nan.

    Plain Python containers are sanitized before encoding — the encoder's
    ``default()`` only fires for non-native types, so a bare ``float('inf')``
    would otherwise slip through as the non-standard ``Infinity`` literal.
    """
    indent = 2 if pretty else None
    return json.dumps(sanitize_for_json(obj), cls=NumpyEncoder, indent=indent)
