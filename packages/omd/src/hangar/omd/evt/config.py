"""Config handling for the native evt model.

evtolpy configs have five sections (``aircraft``, ``mission``, ``power``,
``propulsion``, ``environ``) with units baked into key names. The native model
takes those values as plain OpenMDAO inputs. This module flattens a complete
5-section config into ``{key: value}`` and knows which keys are integer-valued,
so the builders can seed problem inputs and pick per-section defaults.

The section schema is reused from ``hangar.evt.config.defaults`` (pure data, no
evtolpy import) to keep a single source of truth for the known-key sets.
"""

from __future__ import annotations

from typing import Any

from hangar.evt.config.defaults import (  # pure-data import, no evtolpy
    INT_KEYS,
    SECTION_SCHEMA,
    SECTIONS,
)

__all__ = ["SECTIONS", "SECTION_SCHEMA", "INT_KEYS", "flatten_config", "section_of"]

# Reverse index: config key -> section name. Built once from the schema. evtolpy
# key names are unique across sections except where a key legitimately appears in
# two sections (none today), so first-wins over SECTIONS order is deterministic.
_KEY_SECTION: dict[str, str] = {}
for _section in SECTIONS:
    for _key in SECTION_SCHEMA[_section]:
        _KEY_SECTION.setdefault(_key, _section)


def section_of(key: str) -> str | None:
    """Return the section a config key belongs to, or None if unknown."""
    return _KEY_SECTION.get(key)


def flatten_config(base_config: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Flatten a 5-section config into ``{key: value}``.

    Later sections do not override earlier ones; evtolpy keys are unique across
    sections. Integer keys (rotor counts) are coerced to int so disk-area and
    divisor math stays exact.
    """
    flat: dict[str, Any] = {}
    for section in SECTIONS:
        for key, value in base_config.get(section, {}).items():
            flat[key] = int(value) if key in INT_KEYS else value
    return flat
