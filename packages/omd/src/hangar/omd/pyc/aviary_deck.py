"""pyCycle engine deck -> Aviary ``EngineDeck`` (in memory).

Aviary flies an engine from a tabulated deck (Mach, altitude, throttle ->
net thrust, fuel flow) that it normally reads from the CSV named in
``aircraft:engine:data_file``. ``EngineDeck`` takes the same table in
memory (``data=NamedValues``), and ``AviaryGroup.load_external_subsystems``
routes any ``EngineModel`` it is handed into ``engine_models`` in place of
the file deck. This module builds that object from a hangar pyCycle
off-design sweep (``hangar.omd.pyc.surrogate.generate_deck``):

- pyCycle supplies the engine's lapse and SFC characteristics over the
  flight envelope (the deck's shape);
- Aviary scales the deck to the airframe's ``aircraft:engine:
  scaled_sls_thrust`` exactly as it scales any file deck. The reference
  SLS thrust is read off the pyCycle table at the sea-level-static
  full-throttle point, so the grid must include alt 0 / Mach 0 / throttle 1.
  ``data_file``, ``reference_sls_thrust`` and ``scale_factor`` from the
  aircraft deck describe the FLOPS engine and are dropped from the engine
  options; every other ``aircraft:engine:*`` option (engine count, mass
  scaling, flight-idle generation, ...) carries over.

The sweep costs a few seconds per grid point, so decks are cached on disk
under ``<HANGAR_DATA_DIR>/pyc_decks/<sha>.npz``, keyed on the full engine
spec plus the pyCycle version. The omd ``avy/Sizing`` factory and a Lane A
script share one cache; ``cache=False`` forces regeneration.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# provider name (plan config) -> pyCycle archetype (generate_deck)
PROVIDERS: dict[str, str] = {"pyc/hbtf": "hbtf", "pyc/turbojet": "turbojet"}

# Mission-envelope grid for an Aviary deck: includes the SLS full-throttle
# point Aviary needs for reference thrust, and the cruise corner (M 0.8 at
# 37 kft). Throttle stops at 0.5 (T4 ~2330 R for the HBTF archetype): the
# pyCycle HBTF does not converge at lower T4 in much of the envelope, and
# Aviary generates flight idle itself (``generate_flight_idle``). Flight
# conditions pyCycle cannot converge (M 0.25 above 30 kft) drop out of the
# table; Aviary's semi-structured interpolant tolerates that.
DEFAULT_AVIARY_GRID: dict[str, list[float]] = {
    "alt_ft": [0.0, 10000.0, 20000.0, 30000.0, 37000.0],
    "MN": [0.0, 0.25, 0.5, 0.8],
    "throttle": [0.5, 0.7, 0.85, 1.0],
}

STATIC_MN = 1e-6  # pyCycle's sea-level-static Mach (see defaults.py)
# Bump when the sweep procedure changes (guesses, convergence flag): cached
# decks are keyed on it.
SWEEP_VERSION = 2

_CONFIG_KEYS = {
    "design_alt_ft", "design_MN", "design_Fn_lbf", "design_T4_degR",
    "engine_params", "grid",
}


def deck_spec(provider: str, config: dict | None) -> dict[str, Any]:
    """Normalize an engine-deck request into the exact generate_deck inputs.

    Every default is resolved here (not left to generate_deck) so the cache
    key is a function of what actually runs.
    """
    if provider not in PROVIDERS:
        raise ValueError(
            f"engine_deck provider {provider!r} is not one of "
            f"{sorted(PROVIDERS)}."
        )
    config = dict(config or {})
    unknown = set(config) - _CONFIG_KEYS
    if unknown:
        raise ValueError(
            f"engine_deck config has unknown keys {sorted(unknown)}; "
            f"valid keys: {sorted(_CONFIG_KEYS)}."
        )
    archetype = PROVIDERS[provider]

    from hangar.omd.pyc import defaults as defs

    if archetype == "hbtf":
        base = {
            "alt": 35000.0, "MN": 0.8,
            "Fn_target": float(defs.DEFAULT_HBTF_PARAMS["design_Fn"]),
            "T4_target": float(defs.DEFAULT_HBTF_PARAMS["design_T4"]),
        }
    else:
        base = {k: float(v) for k, v in defs.DEFAULT_DESIGN_CONDITIONS.items()}
    design = {
        "alt": float(config.get("design_alt_ft", base["alt"])),
        "MN": float(config.get("design_MN", base["MN"])),
        "Fn_target": float(config.get("design_Fn_lbf", base["Fn_target"])),
        "T4_target": float(config.get("design_T4_degR", base["T4_target"])),
    }
    grid_in = config.get("grid") or DEFAULT_AVIARY_GRID
    try:
        grid = {k: [float(v) for v in grid_in[k]] for k in ("alt_ft", "MN", "throttle")}
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "engine_deck grid needs list-valued 'alt_ft', 'MN' and 'throttle'."
        ) from exc
    if not (0.0 in grid["alt_ft"] and 0.0 in grid["MN"] and 1.0 in grid["throttle"]):
        raise ValueError(
            "engine_deck grid must include alt_ft 0, MN 0 and throttle 1.0: "
            "Aviary reads the reference SLS thrust off that point."
        )
    return {
        "archetype": archetype,
        "design_conditions": design,
        "engine_params": dict(config.get("engine_params") or {}),
        "grid": grid,
    }


def _pycycle_version() -> str:
    try:
        import pycycle

        return str(getattr(pycycle, "__version__", "unknown"))
    except Exception:  # pragma: no cover - pycycle absent
        return "unknown"


def deck_cache_key(spec: dict) -> str:
    payload = json.dumps(
        {"spec": spec, "pycycle": _pycycle_version(), "sweep": SWEEP_VERSION},
        sort_keys=True, default=float,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_cache_dir() -> Path:
    from hangar.sdk.env import _hangar_env

    return Path(_hangar_env("HANGAR_DATA_DIR", "OAS_DATA_DIR", default="./hangar_data")) / "pyc_decks"


def get_or_generate_deck(
    spec: dict, cache: bool | str | Path = True
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Return (deck arrays, info) for a normalized spec, using the disk cache.

    ``cache``: True (default dir), False (always regenerate, never write),
    or a directory path. ``info`` records sha, cache_hit, path, point counts.
    """
    from hangar.omd.pyc.surrogate import generate_deck, load_deck, save_deck

    sha = deck_cache_key(spec)
    info: dict[str, Any] = {"sha": sha, "cache_hit": False, "path": None}
    cache_dir: Path | None
    if cache is False:
        cache_dir = None
    elif cache is True:
        cache_dir = default_cache_dir()
    else:
        cache_dir = Path(cache)
    path = cache_dir / f"{spec['archetype']}_{sha}.npz" if cache_dir else None

    if path is not None and path.exists():
        deck = load_deck(path)
        info.update(cache_hit=True, path=str(path))
    else:
        logger.info("generating pyCycle %s deck (%d points)", spec["archetype"],
                    len(spec["grid"]["alt_ft"]) * len(spec["grid"]["MN"])
                    * len(spec["grid"]["throttle"]))
        # pyCycle cannot evaluate Mach exactly 0 (the flight-condition
        # balance stalls and the point reports its initial guesses); its own
        # SLS convention is MN=1e-6, which Aviary still treats as static
        # (mach_tol 0.01).
        grid = dict(spec["grid"])
        grid["MN"] = [max(m, STATIC_MN) for m in grid["MN"]]
        deck = generate_deck(
            spec["archetype"],
            design_conditions=dict(spec["design_conditions"]),
            engine_params=dict(spec["engine_params"]),
            grid_spec=grid,
        )
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            save_deck(deck, path)
            info["path"] = str(path)
    info["n_points"] = int(len(deck["MN"]))
    info["n_converged"] = int(np.count_nonzero(deck["converged"]))
    return deck, info


def engine_options_from(aviary_inputs, meta_data=None):
    """The aircraft deck's ``aircraft:engine:*`` options for an in-memory deck.

    Mirrors Aviary's ``build_engine_deck`` extraction (first element of
    vectorized values), minus the three options that describe the file
    deck being replaced: ``data_file``, ``reference_sls_thrust`` and
    ``scale_factor``. Aviary then takes the reference thrust from the table
    and derives the scale factor from ``scaled_sls_thrust``.
    """
    from aviary.utils.aviary_values import AviaryValues
    from aviary.utils.utils import isiterable
    from aviary.variable_info.variable_meta_data import CoreMetaData
    from aviary.variable_info.variables import Aircraft

    meta_data = meta_data or CoreMetaData
    drop = {
        Aircraft.Engine.DATA_FILE,
        Aircraft.Engine.REFERENCE_SLS_THRUST,
        Aircraft.Engine.SCALE_FACTOR,
    }
    opts = AviaryValues()
    for var in Aircraft.Engine.__dict__.values():
        if var in drop:
            continue
        try:
            units = meta_data[var]["units"]
        except (KeyError, TypeError):
            continue
        try:
            val = aviary_inputs.get_val(var, units)
        except KeyError:
            continue
        if isiterable(val):
            try:
                first = val[0]
            except TypeError:
                pass
            else:
                if isiterable(first) or len(val) == 1:
                    val = first
        if np.array(val).ndim == 0:
            val = np.array(val).item()
        opts.set_val(var, val, units)
    return opts


def check_deck_sanity(deck: dict[str, np.ndarray]) -> list[str]:
    """Return a list of problems with a pyCycle deck destined for Aviary.

    Aviary's interpolation assumes thrust grows with throttle at a flight
    condition. A failed pyCycle point that slipped through as "converged"
    (stale guesses, 1e14 lbf, identical thrust at every throttle) shows up
    here rather than as NaNs inside the sizing.
    """
    problems: list[str] = []
    mask = usable_mask(deck)
    alt = np.asarray(deck["alt_ft"])[mask]
    mn = np.asarray(deck["MN"])[mask]
    thr = np.asarray(deck["throttle"])[mask]
    fn = np.asarray(deck["thrust_lbf"])[mask]
    for a, m in sorted({(float(x), float(y)) for x, y in zip(alt, mn)}):
        sel = (alt == a) & (mn == m)
        order = np.argsort(thr[sel])
        f = fn[sel][order]
        if not np.all(np.diff(f) > 0.0):
            problems.append(
                f"alt {a:.0f} ft, MN {m:.3f}: thrust not increasing with throttle "
                f"({', '.join(f'{v:.0f}' for v in f)} lbf)"
            )
    return problems


def usable_mask(deck: dict[str, np.ndarray]) -> np.ndarray:
    """Rows Aviary can use: converged, positive thrust, and at a flight
    condition with at least two such throttle points (Aviary's flight-idle
    extrapolation needs two; a lone survivor -- e.g. Mach 0.8 at sea level,
    which no transport flies -- is dropped and the condition falls out of
    the table)."""
    alt = np.asarray(deck["alt_ft"])
    mn = np.asarray(deck["MN"])
    mask = np.asarray(deck["converged"], dtype=bool) & (np.asarray(deck["thrust_lbf"]) > 0.0)
    for a, m in {(float(x), float(y)) for x, y in zip(alt[mask], mn[mask])}:
        sel = mask & (alt == a) & (mn == m)
        if np.count_nonzero(sel) < 2:
            mask[sel] = False
    return mask


def dropped_conditions(deck: dict[str, np.ndarray]) -> list[str]:
    """Flight conditions of the grid with no usable rows (for the run info)."""
    mask = usable_mask(deck)
    alt = np.asarray(deck["alt_ft"])
    mn = np.asarray(deck["MN"])
    grid = {(float(x), float(y)) for x, y in zip(alt, mn)}
    kept = {(float(x), float(y)) for x, y in zip(alt[mask], mn[mask])}
    return [f"alt {a:.0f} ft, MN {m:.3f}" for a, m in sorted(grid - kept)]


def deck_to_named_values(deck: dict[str, np.ndarray]):
    """Usable deck rows as Aviary NamedValues (lb/h fuel)."""
    from aviary.utils.aviary_values import NamedValues

    mask = usable_mask(deck)
    if not mask.any():
        raise ValueError("pyCycle deck has no converged positive-thrust points.")
    data = NamedValues()
    data.set_val("mach", np.asarray(deck["MN"])[mask], "unitless")
    data.set_val("altitude", np.asarray(deck["alt_ft"])[mask], "ft")
    data.set_val("throttle", np.asarray(deck["throttle"])[mask], "unitless")
    data.set_val("thrust", np.asarray(deck["thrust_lbf"])[mask], "lbf")
    data.set_val("fuel_flow", np.asarray(deck["fuel_flow_lbm_s"])[mask] * 3600.0, "lb/h")
    return data, int(mask.sum())


def _pycycle_engine_deck_class():
    from aviary.subsystems.propulsion.engine_deck import EngineDeck
    from aviary.subsystems.propulsion.utils import EngineModelVariables as V

    class PyCycleEngineDeck(EngineDeck):
        """An in-memory EngineDeck with the input/output lists the CSV path
        provides (Aviary 1.0.1 only sets ``inputs``/``outputs`` when it
        reads a file; ``build_mission`` reads them)."""

        def __init__(self, name, options, data, **kwargs):
            super().__init__(name=name, options=options, data=data, **kwargs)
            self.inputs = [V.MACH, V.ALTITUDE, V.THROTTLE]
            self.outputs = [V.THRUST, V.FUEL_FLOW]

    return PyCycleEngineDeck


def build_aviary_engine_deck(
    provider: str,
    config: dict | None,
    aviary_inputs,
    *,
    cache: bool | str | Path = True,
    name: str | None = None,
):
    """Build an Aviary ``EngineDeck`` from a pyCycle sweep; return (deck, info).

    ``aviary_inputs`` is the loaded aircraft ``AviaryValues`` (the source of
    the non-deck engine options). Hand the returned EngineDeck to
    ``load_external_subsystems`` alongside any other builders.
    """
    from aviary.variable_info.variables import Aircraft

    spec = deck_spec(provider, config)
    deck, info = get_or_generate_deck(spec, cache=cache)
    problems = check_deck_sanity(deck)
    if problems:
        raise ValueError(
            f"pyCycle {spec['archetype']} deck is not usable as an Aviary engine "
            f"deck ({len(problems)} flight conditions):\n  " + "\n  ".join(problems)
            + "\nAdjust the engine_deck grid (drop the offending throttle/Mach "
            "values) or the design conditions."
        )
    data, n_used = deck_to_named_values(deck)
    engine = _pycycle_engine_deck_class()(
        name=name or provider.replace("/", "_"),
        options=engine_options_from(aviary_inputs),
        data=data,
    )
    info.update(
        provider=provider,
        spec=spec,
        n_used=n_used,
        dropped_conditions=dropped_conditions(deck),
        reference_sls_thrust_lbf=float(
            np.ravel(engine.get_val(Aircraft.Engine.REFERENCE_SLS_THRUST, "lbf"))[0]
        ),
    )
    return engine, info


__all__ = [
    "PROVIDERS",
    "DEFAULT_AVIARY_GRID",
    "deck_spec",
    "deck_cache_key",
    "default_cache_dir",
    "get_or_generate_deck",
    "engine_options_from",
    "check_deck_sanity",
    "usable_mask",
    "dropped_conditions",
    "deck_to_named_values",
    "build_aviary_engine_deck",
]
