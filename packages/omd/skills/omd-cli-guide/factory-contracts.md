# Factory Contracts

Authoring guide for the `FactoryContract` declaration on omd component
factories. Contracts power the `composition_policy: auto` shared-var
auto-derivation introduced in Fix 3 (Phase 3a). If you are adding a new
factory to omd or extending an existing one, this is where you declare
what promoted inputs the factory drives by default.

## Why contracts exist

A composite plan with two or more OCP missions that both read
`ac|geom|wing|AR` used to require a hand-written `shared_vars:` block.
With a declared contract, the materializer can see that both components
claim to produce `ac|geom|wing|AR` and hoist it to a root
`shared_ivc` automatically. The mechanism is identical to Fix 2's
`skip_fields` + root IVC fanout — only the *decision* to hoist is
moved from the plan author to the factory author.

## The dataclasses

```python
from hangar.omd.factory_metadata import FactoryContract, VarSpec

contract = FactoryContract(
    produces={
        "ac|geom|wing|AR": VarSpec(
            default=9.45,
            semantic_tag="geometry",
            description="Wing aspect ratio",
        ),
        "v": VarSpec(
            units="m/s",
            default=248.136,
            semantic_tag="flight_condition",
        ),
        "empty_cg": VarSpec(
            shape=(3,),
            units="m",
            default=[0.35, 0.0, 0.0],
            semantic_tag="flight_condition",
        ),
    },
    consumes={
        # Promoted inputs the factory reads but does not drive.
        # Informational today; reserved for future cross-tool
        # translation work.
    },
)
```

Both dataclasses are frozen. `produces` and `consumes` are wrapped in
`MappingProxyType` at construction so the declarations cannot be
mutated at runtime.

### `VarSpec` fields

| Field | Meaning |
|-------|---------|
| `shape` | `tuple[int, ...]` or `None`. `None` means scalar (OpenMDAO infers `(1,)`). |
| `units` | OpenMDAO units string, or `None` for "template-dependent / don't check". |
| `default` | Value passed to `add_output(val=...)` if this factory is the canonical producer in auto-share. Scalar, list, or numpy array. |
| `semantic_tag` | One of `geometry`, `flight_condition`, `material`, `propulsion`, `weight`, `mission_param`, or `None`. Informational today. |
| `description` | One-line human-readable description. |

### Which names go in `produces`?

Include a name in `produces` when the factory, by default, creates an
IndepVarComp output at the model root (via promotion) for that name.
That is: in the default code path, the name is driven internally. With
`skip_fields=[name]`, the factory must stop driving it so the root
`shared_ivc` can take over.

Do NOT include:

- Conditional fields whose presence depends on architecture/template
  choices. Users can still share these via explicit `shared_vars:`.
  Example: OCP's `_HYBRID_FIELDS` only register when the architecture
  is hybrid; they are explicit-only.
- Geometry subsystem outputs (OAS `twist_cp`, `chord_cp`,
  `t_over_c_cp`). These live inside a Geometry group, not in the
  flight-condition IVC, and the shared-IVC fanout does not apply.
- Vectorized IVCs whose shape depends on runtime config
  (`oas/AerostructMultipoint` varies shape with `flight_points`).
  Phase 3a leaves these explicit-only; their contract is declared
  empty.

### Declaring units

Declare `units=None` when the factory reads its units from the
incoming data dict (e.g., OCP DictIndepVarComp). Units are only
checked by the integrity validator when the contract pins them.
Plan-level `set_val` with explicit units still works regardless of
what the contract declares.

## Attaching the contract

The contract is attached as a plain attribute on the registered
factory function — same pattern as slot providers
(`slot.design_variables`, `slot.result_paths`, `slot.slot_scope`).

```python
def build_my_factory(component_config, operating_points):
    ...
    return prob, metadata


build_my_factory.contract = FactoryContract(
    produces={...},
    consumes={},
)
```

Re-exports through an `__init__.py` preserve the attribute because it
is bound to the function object, not imported by name.

## Honoring `skip_fields`

A factory that declares `produces[name]` MUST honor
`component_config["skip_fields"] = [name]` by omitting the IVC output
for that name. Existing OMD factories already do this for Fix 2
(`factories/oas.py:439`, `factories/oas_aero.py:156`,
`factories/ocp/builder.py:113`). The pattern is:

```python
skip_fields = set(component_config.get("skip_fields") or [])

def _add(name, **kw):
    if name in skip_fields:
        return
    indep.add_output(name, **kw)

_add("v", val=flight["velocity"], units="m/s")
```

When a name is skipped, the promoted input remains visible at the
model root but has no internal source. The root `shared_ivc` (added
by the materializer) drives it.

## Integrity tests

`packages/omd/tests/test_factory_contracts.py` parameterizes a
two-pass check over every registered factory with a declared
contract:

- **Pass 1**: call the factory with default config, `final_setup()`,
  and assert every name in `produces` appears as a promoted root
  variable (input or IVC-driven output) with matching shape and
  (when declared) units.
- **Pass 2**: re-run the factory once per produced name with that
  name in `skip_fields`. Confirm the internal IVC source for the
  name disappears (OpenMDAO shows `_auto_ivc` or no source instead).

New factories add an entry in `_FIXTURES` mapping
`component_type` → `(default_config, default_operating_points)` and
the parameterized test picks them up automatically.

## Relation to Fix 2

Contracts are purely *declarative*. A plan with
`composition_policy: auto` fans them into implicit `shared_vars`
entries; the downstream materialization code (`consumer_skip_fields`
injection, root `shared_ivc`, fanout connections, `var_paths` merge)
is unchanged from Fix 2. Turning off `composition_policy`
(the default, `explicit`) makes contracts a no-op — Fix 2 plans
continue to work byte-identically.

## What's out of scope for Phase 3a

- Auto-sharing across tool boundaries (ocp ↔ oas). Contracts can
  carry `semantic_tag`, but the materializer only hoists on exact
  name match. Cross-tool work is a Phase 3b+ concern.
- `VarSpec.role = "source" | "exposed_ivc"` for distinguishing
  factories that actually write the value vs merely expose it.
- Per-instance contract variation (contracts are attached once per
  factory function; different configs on the same factory cannot
  declare different contracts).
