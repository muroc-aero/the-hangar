"""Input validation for Aviary MCP tools.

Raises ValueError with clear messages (and typo suggestions) for invalid
inputs. Deck-variable name validation happens lazily against Aviary's
variable metadata so this module stays importable without aviary.
"""

from __future__ import annotations

import difflib


def validate_aircraft_exists(session, aircraft_name: str) -> dict:
    """Validate aircraft exists in session, return its config."""
    aircraft = session.aircraft
    if aircraft_name not in aircraft:
        available = list(aircraft.keys())
        raise ValueError(
            f"Aircraft {aircraft_name!r} not found. Available aircraft: {available}. "
            f"Call load_aircraft_template first."
        )
    return aircraft[aircraft_name]


def validate_deck_overrides(overrides: dict) -> None:
    """Validate override variable names against Aviary's variable metadata."""
    from hangar.avy.runner import require_aviary

    require_aviary()
    from aviary.variable_info.variable_meta_data import _MetaData

    for name, spec in overrides.items():
        if name not in _MetaData:
            close = difflib.get_close_matches(name, _MetaData.keys(), n=3)
            hint = f" Close matches: {close}." if close else ""
            raise ValueError(
                f"Unknown Aviary variable {name!r} in overrides. Names use the "
                f"'aircraft:wing:span' hierarchy from aviary's variable metadata."
                f"{hint}"
            )
        if isinstance(spec, (list, tuple)):
            if len(spec) != 2 or not isinstance(spec[1], str):
                raise ValueError(
                    f"Override for {name!r} must be a bare value or a "
                    f"[value, units] pair (got {spec!r})."
                )


def validate_max_iter(max_iter: int) -> None:
    if not (1 <= max_iter <= 500):
        raise ValueError(f"max_iter must be in [1, 500] (got {max_iter})")
