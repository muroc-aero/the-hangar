"""``omd://reference`` must name every registered component type.

2026-09-21: ``avy/Sizing`` was registered on 09-19 and never added to the
reference's type table; 4 of 5 gemma seeds on ``avy_single_aisle`` followed
the reference and picked ``ocp/FullMission`` with the b738 template as a
"proxy" for an Aviary sizing task.
"""

from __future__ import annotations

from pathlib import Path

from hangar.omd.registry import list_factories

_REFERENCE = Path(__file__).resolve().parents[1] / "src" / "hangar" / "omd" / "reference.md"


def test_every_registered_component_type_is_in_the_reference():
    text = _REFERENCE.read_text(encoding="utf-8")
    missing = [t for t in list_factories() if f"`{t}`" not in text]
    assert missing == [], f"registered but undocumented in reference.md: {missing}"


def test_the_reference_says_where_oas_surface_keys_go():
    text = _REFERENCE.read_text(encoding="utf-8")
    assert "INSIDE a surface entry" in text
    assert "`avy/Sizing`" in text and "mode: optimize" in text
