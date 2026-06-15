"""Assemble an evtolpy ``Aircraft`` from a session config dict.

evtolpy's ``Aircraft`` constructor only accepts a path to a JSON file, so the
builder serializes the in-memory config to a temporary JSON file and constructs
from that. Construction is cheap (it just parses JSON and builds the sub-object
classes); the physics runs lazily on property access.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from hangar.evt.config.defaults import SECTIONS


def merged_config(base: dict | None, section: str, overrides: dict) -> dict:
    """Return a copy of ``base`` config with ``overrides`` merged into ``section``."""
    cfg: dict[str, dict] = {k: dict(v) for k, v in (base or {}).items()}
    cfg.setdefault(section, {})
    cfg[section].update(overrides)
    return cfg


def assert_complete(config: dict) -> None:
    """Raise ValueError if any required section is missing.

    The upstream constructor indexes config keys directly, so an incomplete
    config fails with a bare ``KeyError`` deep inside evtolpy. Fail early with
    a clear message instead.
    """
    missing = [s for s in SECTIONS if not config.get(s)]
    if missing:
        raise ValueError(
            f"Vehicle config is incomplete -- missing section(s): {missing}. "
            f"Load a template with load_vehicle_template first, then apply "
            f"overrides with define_vehicle / configure_mission / set_power / "
            f"set_propulsion / set_environment."
        )


def build_aircraft(config: dict) -> Any:
    """Construct an evtolpy ``Aircraft`` from a complete config dict.

    Writes the config to a temp JSON file (the only constructor input evtolpy
    accepts) and builds the aircraft. The temp file is removed before returning.
    """
    # Imported lazily so importing this module does not require evtolpy.
    from evtol.aircraft import Aircraft

    assert_complete(config)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        json.dump(config, tmp)
        tmp.flush()
        tmp.close()
        return Aircraft(tmp.name)
    finally:
        Path(tmp.name).unlink(missing_ok=True)
