"""Shared surface definitions for hangar-oas tests.

Lives outside conftest.py so test modules can import the constants by a
unique module name. Importing from conftest breaks when several packages'
test suites are collected in one pytest run: every conftest.py without an
``__init__.py`` imports as the module ``conftest``, and ``from conftest
import ...`` resolves to whichever one loaded first.
"""

# Tiny mesh used across integration tests — fast but produces real results.
SMALL_RECT = dict(
    name="wing",
    wing_type="rect",
    span=10.0,
    root_chord=1.0,
    num_x=2,
    num_y=5,   # smallest valid odd value
    symmetry=True,
    with_viscous=True,
)

SMALL_RECT_STRUCT = dict(
    **SMALL_RECT,
    fem_model_type="tube",
    E=70.0e9,
    G=30.0e9,
    yield_stress=500.0e6,
    safety_factor=2.5,
    mrho=3.0e3,
    thickness_cp=[0.05, 0.1, 0.05],
)

SMALL_RECT_WINGBOX = dict(
    **SMALL_RECT,
    fem_model_type="wingbox",
    E=73.1e9,
    G=27.5e9,
    yield_stress=420.0e6,
    safety_factor=1.5,
    mrho=2.78e3,
)

# Tail surface for multi-surface tests — positioned behind and above the wing.
SMALL_TAIL = dict(
    name="tail",
    wing_type="rect",
    span=4.0,
    root_chord=0.8,
    num_x=2,
    num_y=5,
    symmetry=True,
    with_viscous=True,
    offset=[5.0, 0.0, 0.5],
)

SMALL_TAIL_STRUCT = dict(
    **SMALL_TAIL,
    fem_model_type="tube",
    E=70.0e9,
    G=30.0e9,
    yield_stress=500.0e6,
    safety_factor=2.5,
    mrho=3.0e3,
    thickness_cp=[0.03, 0.05, 0.03],
)
