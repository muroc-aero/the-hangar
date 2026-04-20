"""Plan authoring subcommands (`omd-cli plan ...`)."""

from __future__ import annotations

import json
from pathlib import Path

import click

from hangar.omd.cli import cli


@cli.group("plan")
def plan_group() -> None:
    """Plan authoring commands (init, add-*, set-*, review)."""


# ---------------------------------------------------------------------------
# Plan authoring helpers
# ---------------------------------------------------------------------------

def _plan_error_exit(exc: Exception) -> None:
    """Print a UserInputError and exit(1)."""
    click.echo(f"Error: {exc}", err=True)
    raise SystemExit(1)


def _prompt(value, label: str, *, cast=str, default=None):
    """Click prompt if the current value is None, else pass through."""
    if value is not None:
        return value
    if default is None:
        return click.prompt(label, type=cast)
    return click.prompt(label, type=cast, default=default)


def _require_interactive_rationale(rationale: str | None) -> str:
    """Under --interactive, the user must supply a non-empty rationale."""
    if rationale is None:
        rationale = click.prompt("Rationale", default="", show_default=False)
    if not rationale.strip():
        click.echo(
            "Error: --interactive requires a non-empty rationale.",
            err=True,
        )
        raise SystemExit(1)
    return rationale


@plan_group.command("review")
@click.argument("plan_path", type=click.Path(exists=True))
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", help="Output format")
def plan_review_cmd(plan_path: str, fmt: str) -> None:
    """Review an assembled plan (or plan directory) for completeness.

    Emits WARN / MISSING / ERROR findings covering requirements,
    decisions, analysis_plan, rationale, and graph completeness. Exit
    code is always 0 -- the checker is advisory. Use ``--format json``
    for machine-readable output.
    """
    from hangar.omd.plan_review import (
        format_findings_json,
        format_findings_text,
        review_plan_file,
    )

    plan, findings = review_plan_file(Path(plan_path))
    if fmt == "json":
        click.echo(format_findings_json(plan, findings))
    else:
        click.echo(format_findings_text(plan, findings))


# ---------------------------------------------------------------------------
# Plan authoring subcommands (init / add-* / set-*)
# ---------------------------------------------------------------------------

@plan_group.command("init")
@click.argument("plan_dir", type=click.Path(file_okay=False))
@click.option("--id", "plan_id", default=None, help="Plan id")
@click.option("--name", default=None, help="Plan name")
@click.option("--description", default=None, help="Optional description")
@click.option("--interactive", "-i", is_flag=True)
def plan_init_cmd(
    plan_dir: str,
    plan_id: str | None,
    name: str | None,
    description: str | None,
    interactive: bool,
) -> None:
    """Scaffold a plan directory with metadata.yaml only."""
    from hangar.omd.plan_mutate import init_plan
    from hangar.sdk.errors import UserInputError

    if interactive:
        plan_id = _prompt(plan_id, "Plan id")
        name = _prompt(name, "Plan name")
        if description is None:
            description = click.prompt(
                "Description", default="", show_default=False,
            ) or None
    if not plan_id or not name:
        _plan_error_exit(
            UserInputError("--id and --name are required "
                           "(or pass --interactive)"),
        )
    try:
        init_plan(
            Path(plan_dir),
            plan_id=plan_id,
            name=name,
            description=description,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Initialized plan at {plan_dir} (id={plan_id})")


@plan_group.command("add-component")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--id", "comp_id", default=None, help="Component id")
@click.option("--type", "comp_type", default=None,
              help="Component type (e.g. oas/AerostructPoint)")
@click.option("--config-file", type=click.Path(exists=True, dir_okay=False),
              default=None, help="YAML file with the component config")
@click.option("--rationale", default=None,
              help="Why (captured to decisions.yaml)")
@click.option("--interactive", "-i", is_flag=True)
@click.option("--replace", is_flag=True)
def plan_add_component_cmd(
    plan_dir: str,
    comp_id: str | None,
    comp_type: str | None,
    config_file: str | None,
    rationale: str | None,
    interactive: bool,
    replace: bool,
) -> None:
    """Add a component to the plan.

    Non-interactive use requires --config-file. Interactive use prompts
    for a curated field list when --type is oas/AerostructPoint, and
    otherwise opens $EDITOR for paste-in YAML.
    """
    import yaml

    from hangar.omd.plan_mutate import add_component
    from hangar.sdk.errors import UserInputError

    if interactive:
        comp_id = _prompt(comp_id, "Component id")
        comp_type = _prompt(
            comp_type, "Component type", default="oas/AerostructPoint",
        )
        rationale = _require_interactive_rationale(rationale)
        config = _prompt_component_config(comp_type, config_file)
    else:
        if not comp_id or not comp_type:
            _plan_error_exit(
                UserInputError(
                    "--id and --type are required (or pass --interactive)"
                )
            )
        if not config_file:
            _plan_error_exit(
                UserInputError(
                    "--config-file is required in non-interactive mode"
                )
            )
        config = yaml.safe_load(Path(config_file).read_text())
        if not isinstance(config, dict):
            _plan_error_exit(
                UserInputError("config-file must contain a YAML mapping")
            )

    try:
        add_component(
            Path(plan_dir),
            comp_id=comp_id,
            comp_type=comp_type,
            config=config,
            rationale=rationale,
            replace=replace,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Added component {comp_id} ({comp_type})")


def _prompt_component_config(comp_type: str, config_file: str | None) -> dict:
    """Return a component config dict for interactive add-component."""
    import yaml

    if config_file:
        data = yaml.safe_load(Path(config_file).read_text())
        if isinstance(data, dict):
            return data
    if comp_type == "oas/AerostructPoint":
        surface_name = click.prompt("Surface name", default="wing")
        wing_type = click.prompt(
            "wing_type", default="rect",
            type=click.Choice(["rect", "CRM"], case_sensitive=False),
        )
        num_x = click.prompt("num_x", type=int, default=2)
        num_y = click.prompt("num_y (odd integer)", type=int, default=7)
        span = click.prompt("span", type=float, default=10.0)
        root_chord = click.prompt("root_chord", type=float, default=1.0)
        symmetry = click.confirm("symmetry?", default=True)
        fem_model_type = click.prompt(
            "fem_model_type", default="tube",
            type=click.Choice(["tube", "wingbox"], case_sensitive=False),
        )
        E = click.prompt("E (Young's modulus, Pa)", type=float, default=7.0e10)
        G = click.prompt("G (shear modulus, Pa)", type=float, default=3.0e10)
        yield_stress = click.prompt(
            "yield_stress (Pa)", type=float, default=5.0e8,
        )
        mrho = click.prompt(
            "mrho (material density, kg/m^3)", type=float, default=3000.0,
        )
        return {
            "surfaces": [{
                "name": surface_name,
                "wing_type": wing_type,
                "num_x": num_x,
                "num_y": num_y,
                "span": span,
                "root_chord": root_chord,
                "symmetry": symmetry,
                "fem_model_type": fem_model_type,
                "E": E,
                "G": G,
                "yield_stress": yield_stress,
                "mrho": mrho,
            }],
        }
    # Unknown type: fall back to edit-in-editor
    template = "# Paste the component config YAML below\n"
    edited = click.edit(template)
    if not edited:
        raise click.ClickException("No config provided")
    data = yaml.safe_load(edited)
    if not isinstance(data, dict):
        raise click.ClickException("Edited config must be a YAML mapping")
    return data


@plan_group.command("add-requirement")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--id", "req_id", default=None)
@click.option("--text", default=None)
@click.option("--type", "req_type", default=None,
              help="performance/structural/stability/constraint/objective")
@click.option("--priority", default=None,
              type=click.Choice(["primary", "secondary", "goal"]))
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
@click.option("--replace", is_flag=True)
def plan_add_requirement_cmd(
    plan_dir: str,
    req_id: str | None,
    text: str | None,
    req_type: str | None,
    priority: str | None,
    rationale: str | None,
    interactive: bool,
    replace: bool,
) -> None:
    """Append a requirement to requirements.yaml."""
    from hangar.omd.plan_mutate import add_requirement
    from hangar.sdk.errors import UserInputError

    if interactive:
        req_id = _prompt(req_id, "Requirement id (e.g. R1)")
        text = _prompt(text, "Text")
        if req_type is None:
            req_type = click.prompt(
                "Type",
                default="",
                show_default=False,
            ) or None
        if priority is None:
            priority = click.prompt(
                "Priority",
                default="",
                show_default=False,
            ) or None
        rationale = _require_interactive_rationale(rationale)
    if not req_id or not text:
        _plan_error_exit(
            UserInputError(
                "--id and --text are required (or pass --interactive)"
            )
        )

    req: dict = {"id": req_id, "text": text}
    if req_type:
        req["type"] = req_type
    if priority:
        req["priority"] = priority
    try:
        add_requirement(
            Path(plan_dir), req=req, rationale=rationale, replace=replace,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Added requirement {req_id}")


@plan_group.command("add-dv")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--name", default=None, help="DV short or prefixed name")
@click.option("--lower", type=float, default=None)
@click.option("--upper", type=float, default=None)
@click.option("--scaler", type=float, default=None)
@click.option("--units", default=None)
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
@click.option("--replace", is_flag=True)
def plan_add_dv_cmd(
    plan_dir: str,
    name: str | None,
    lower: float | None,
    upper: float | None,
    scaler: float | None,
    units: str | None,
    rationale: str | None,
    interactive: bool,
    replace: bool,
) -> None:
    """Add a design variable to optimization.yaml."""
    from hangar.omd.plan_mutate import _collect_var_paths, add_dv
    from hangar.sdk.errors import UserInputError

    if interactive:
        allowed = sorted(_collect_var_paths(Path(plan_dir)))
        if allowed:
            click.echo(f"Allowed DV short names: {', '.join(allowed)}")
        else:
            click.echo(
                "No components declared yet — "
                "DV names will not be strictly validated.",
            )
        name = _prompt(name, "DV name")
        lower = _prompt(lower, "Lower bound", cast=float)
        upper = _prompt(upper, "Upper bound", cast=float)
        rationale = _require_interactive_rationale(rationale)
    if name is None or lower is None or upper is None:
        _plan_error_exit(
            UserInputError(
                "--name, --lower, --upper are required "
                "(or pass --interactive)"
            )
        )
    try:
        add_dv(
            Path(plan_dir),
            name=name, lower=lower, upper=upper,
            scaler=scaler, units=units,
            rationale=rationale, replace=replace,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Added DV {name}: [{lower}, {upper}]")


@plan_group.command("set-objective")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--name", default=None)
@click.option("--scaler", type=float, default=None)
@click.option("--units", default=None)
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_set_objective_cmd(
    plan_dir: str,
    name: str | None,
    scaler: float | None,
    units: str | None,
    rationale: str | None,
    interactive: bool,
) -> None:
    """Set the optimization objective."""
    from hangar.omd.plan_mutate import _collect_var_paths, set_objective
    from hangar.sdk.errors import UserInputError

    if interactive:
        allowed = sorted(_collect_var_paths(Path(plan_dir)))
        if allowed:
            click.echo(f"Allowed objective names: {', '.join(allowed)}")
        else:
            click.echo(
                "No components declared yet — "
                "objective name will not be strictly validated.",
            )
        name = _prompt(name, "Objective name")
        if scaler is None:
            scaler_input = click.prompt(
                "Scaler (blank for none)",
                default="", show_default=False,
            )
            scaler = float(scaler_input) if scaler_input.strip() else None
        rationale = _require_interactive_rationale(rationale)
    if name is None:
        _plan_error_exit(
            UserInputError("--name is required (or pass --interactive)")
        )
    try:
        set_objective(
            Path(plan_dir),
            name=name, scaler=scaler, units=units, rationale=rationale,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Objective: {name}")


@plan_group.command("add-decision")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--id", "dec_id", default=None, help="Decision id (auto if omitted)")
@click.option("--stage", default=None,
              help="One of the recommended stages; off-list emits a warning")
@click.option("--decision", "decision_text", default=None,
              help="What was decided")
@click.option("--rationale", default=None, help="Why")
@click.option("--element-path", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_add_decision_cmd(
    plan_dir: str,
    dec_id: str | None,
    stage: str | None,
    decision_text: str | None,
    rationale: str | None,
    element_path: str | None,
    interactive: bool,
) -> None:
    """Append a hand-authored decision entry."""
    from hangar.omd.plan_mutate import add_decision
    from hangar.omd.plan_schema import RECOMMENDED_DECISION_STAGES
    from hangar.sdk.errors import UserInputError

    if interactive:
        click.echo(
            "Recommended stages: " + ", ".join(RECOMMENDED_DECISION_STAGES)
        )
        stage = _prompt(stage, "Stage")
        decision_text = _prompt(decision_text, "Decision")
        rationale = _require_interactive_rationale(rationale)
        if element_path is None:
            element_path = click.prompt(
                "Element path (blank for none)",
                default="", show_default=False,
            ) or None
    if not stage or not decision_text:
        _plan_error_exit(
            UserInputError(
                "--stage and --decision are required (or pass --interactive)"
            )
        )
    if stage not in RECOMMENDED_DECISION_STAGES:
        click.echo(
            f"Warning: stage '{stage}' is not in RECOMMENDED_DECISION_STAGES "
            "(plan review will flag it).",
            err=True,
        )

    entry: dict = {"stage": stage, "decision": decision_text}
    if dec_id:
        entry["id"] = dec_id
    if rationale:
        entry["rationale"] = rationale
    if element_path:
        entry["element_path"] = element_path

    try:
        written = add_decision(Path(plan_dir), decision=entry)
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Added decision {written.get('id')}")


@plan_group.command("set-operating-point")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--mach", type=float, default=None, help="Mach_number")
@click.option("--alpha", type=float, default=None, help="Angle of attack (deg)")
@click.option("--velocity", type=float, default=None, help="Velocity (m/s)")
@click.option("--altitude", type=float, default=None, help="Altitude (m or ft per --units)")
@click.option("--re", "reynolds", type=float, default=None, help="Reynolds number")
@click.option("--rho", type=float, default=None, help="Density (kg/m^3)")
@click.option("--units", type=click.Choice(["SI", "imperial"]),
              default="SI", help="Altitude units only: m (SI) or ft (imperial)")
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_set_operating_point_cmd(
    plan_dir: str,
    mach: float | None,
    alpha: float | None,
    velocity: float | None,
    altitude: float | None,
    reynolds: float | None,
    rho: float | None,
    units: str,
    rationale: str | None,
    interactive: bool,
) -> None:
    """Merge operating-point fields into operating_points.yaml."""
    from hangar.omd.plan_mutate import set_operating_point
    from hangar.sdk.errors import UserInputError

    if interactive:
        if mach is None:
            mach_in = click.prompt(
                "Mach_number", default="", show_default=False,
            )
            mach = float(mach_in) if mach_in.strip() else None
        if alpha is None:
            alpha_in = click.prompt(
                "alpha (deg)", default="", show_default=False,
            )
            alpha = float(alpha_in) if alpha_in.strip() else None
        if velocity is None:
            v_in = click.prompt(
                "velocity (m/s, blank for none)",
                default="", show_default=False,
            )
            velocity = float(v_in) if v_in.strip() else None
        if altitude is None:
            alt_in = click.prompt(
                f"altitude ({'m' if units == 'SI' else 'ft'}, blank for none)",
                default="", show_default=False,
            )
            altitude = float(alt_in) if alt_in.strip() else None
        rationale = _require_interactive_rationale(rationale)

    fields: dict = {}
    if mach is not None:
        fields["Mach_number"] = mach
    if alpha is not None:
        fields["alpha"] = alpha
    if velocity is not None:
        fields["velocity"] = velocity
    if altitude is not None:
        alt_units = "m" if units == "SI" else "ft"
        fields["altitude"] = {"value": altitude, "units": alt_units}
    if reynolds is not None:
        fields["re"] = reynolds
    if rho is not None:
        fields["rho"] = rho

    if not fields:
        _plan_error_exit(
            UserInputError("no fields provided (pass at least one of "
                           "--mach, --alpha, --velocity, --altitude, "
                           "--re, --rho)")
        )
    try:
        set_operating_point(
            Path(plan_dir), fields=fields, rationale=rationale,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Updated operating point: {sorted(fields)}")


@plan_group.command("set-solver")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--nonlinear", default=None, help="e.g. NewtonSolver")
@click.option("--linear", default=None, help="e.g. DirectSolver")
@click.option("--nonlinear-maxiter", type=int, default=None)
@click.option("--nonlinear-atol", type=float, default=None)
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_set_solver_cmd(
    plan_dir: str,
    nonlinear: str | None,
    linear: str | None,
    nonlinear_maxiter: int | None,
    nonlinear_atol: float | None,
    rationale: str | None,
    interactive: bool,
) -> None:
    """Set the nonlinear / linear solver types for solvers.yaml."""
    from hangar.omd.plan_mutate import set_solver
    from hangar.sdk.errors import UserInputError

    if interactive:
        nonlinear = _prompt(
            nonlinear, "Nonlinear solver", default="NewtonSolver",
        ) or None
        linear = _prompt(linear, "Linear solver", default="DirectSolver") or None
        rationale = _require_interactive_rationale(rationale)

    nl_options: dict = {}
    if nonlinear_maxiter is not None:
        nl_options["maxiter"] = nonlinear_maxiter
    if nonlinear_atol is not None:
        nl_options["atol"] = nonlinear_atol

    try:
        set_solver(
            Path(plan_dir),
            nonlinear=nonlinear,
            linear=linear,
            nonlinear_options=nl_options or None,
            rationale=rationale,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    parts = []
    if nonlinear:
        parts.append(f"nonlinear={nonlinear}")
    if linear:
        parts.append(f"linear={linear}")
    click.echo("Solvers: " + ", ".join(parts))


@plan_group.command("set-analysis-strategy")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--phases", type=int, default=None,
              help="Number of phases to scaffold")
@click.option("--phase-id-prefix", default="p",
              help="Prefix for phase ids (default: p)")
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_set_analysis_strategy_cmd(
    plan_dir: str,
    phases: int | None,
    phase_id_prefix: str,
    rationale: str | None,
    interactive: bool,
) -> None:
    """Scaffold analysis_plan.yaml with N empty phases (user fills in)."""
    from hangar.omd.plan_mutate import set_analysis_strategy
    from hangar.sdk.errors import UserInputError

    if interactive:
        phases = _prompt(phases, "Number of phases", cast=int, default=2)
        rationale = _require_interactive_rationale(rationale)
    if phases is None:
        _plan_error_exit(
            UserInputError("--phases is required (or pass --interactive)")
        )
    try:
        set_analysis_strategy(
            Path(plan_dir),
            phases=phases,
            phase_id_prefix=phase_id_prefix,
            rationale=rationale,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Scaffolded {phases} phases "
               f"({phase_id_prefix}1..{phase_id_prefix}{phases})")

