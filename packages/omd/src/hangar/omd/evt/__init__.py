"""Native OpenMDAO formulation of the evtolpy eVTOL sizing model.

This subpackage reimplements evtolpy's physics as idiomatic OpenMDAO
components and groups, so eVTOL sizing can be driven by gradient-based
optimizers and coupled into a single converged solver with OAS or pyCycle.
It is a faithful transcription of upstream evtolpy (`upstream/evtolpy/evtol/`):
every equation matches the source, and the parity suite asserts agreement with
the black-box wrapper (`hangar.evt.omd_component.EvtolSizingComp`) to floating
point.

Design rules (see ``packages/evt/docs/native-openmdao-rewrite-implementation-plan.md``):

* Depend only on ``numpy`` and ``openmdao`` -- never on ``evtolpy`` or
  ``hangar.evt`` physics at runtime (the config-schema constants in
  ``hangar.evt.config.defaults`` are pure data and are the one allowed import,
  used only by the builders). This keeps the package importable in the
  dashboard env.
* All component ``compute`` methods use ``numpy`` math (``np.sqrt``,
  ``np.log10``, ``np.arctan2`` ...) so they are complex-safe. Components declare
  ``declare_partials("*", "*", method="cs")`` and the problem is set up with
  ``force_alloc_complex=True``; OpenMDAO then complex-steps each component for
  exact partials with no hand-derived Jacobians.
* Variable names are the evtolpy property/attribute names (``wing_area_m2``,
  ``cruise_l_p_d`` ...) so the model graph reads like the source.
"""

from __future__ import annotations
