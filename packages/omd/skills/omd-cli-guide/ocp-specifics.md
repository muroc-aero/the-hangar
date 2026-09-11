# OCP-Specific Notes

Deep-dive companion to `SKILL.md` covering custom aircraft data for
OCP missions and OCP-specific solver settings.

## Custom Aircraft Data

Instead of using `aircraft_template`, define aircraft inline with
`aircraft_data`. The nested dict uses pipe-separated keys matching
OpenConcept conventions:

```yaml
components:
- id: mission
  type: ocp/BasicMission
  config:
    aircraft_data:
      ac:
        aero:
          CLmax_TO:
            value: 2.1
          polar:
            e:
              value: 0.82
            CD0_TO:
              value: 0.032
            CD0_cruise:
              value: 0.019
        geom:
          wing:
            S_ref:
              value: 122.6
              units: "m**2"
            AR:
              value: 9.5
            c4sweep:
              value: 25.0
              units: deg
            taper:
              value: 0.24
            toverc:
              value: 0.12
          hstab:
            S_ref:
              value: 31.0
              units: "m**2"
            c4_to_wing_c4:
              value: 17.5
              units: m
          vstab:
            S_ref:
              value: 21.5
              units: "m**2"
          nosegear:
            length:
              value: 3
              units: ft
          maingear:
            length:
              value: 4
              units: ft
        weights:
          MTOW:
            value: 78000
            units: kg
          OEW:
            value: 42600
            units: kg
          W_fuel_max:
            value: 19000
            units: kg
          MLW:
            value: 64500
            units: kg
        propulsion:
          engine:
            rating:
              value: 27000
              units: lbf
        num_passengers_max:
          value: 180
        q_cruise:
          value: 210.0
          units: "lb*ft**-2"
    architecture: twin_turbofan
```

## OCP Solver Settings

OCP missions accept `solver_settings` in the component config:

```yaml
solver_settings:
  solver_type: newton    # "newton" (default) or "nlbgs"
  maxiter: 20            # max iterations (default 20)
  atol: 1.0e-10          # absolute tolerance
  rtol: 1.0e-10          # relative tolerance
  solve_subsystems: true  # Newton solve_subsystems (default true)
  use_aitken: true        # NLBGS Aitken relaxation (default true)
```

**Always use `newton` for a mission.** OpenConcept's mission groups carry
no solvers of their own, and every phase contains three `BalanceComp`s --
throttle (thrust = drag), alpha (to hit the target CL), and phase duration.
Only a residual-driving solver closes those.

`nlbgs` does **not**. `NonlinearBlockGS` only *calls* each subsystem's
`_solve_nonlinear`, and a `BalanceComp` defines none, so every balance keeps
its initial value -- throttle frozen at 0.5, alpha at 1 deg -- while NLBGS
reports convergence in a handful of iterations. The numbers it returns are
the initial guesses propagated through the explicit components, not a
solution. Do not reach for `nlbgs` to quiet a Newton that will not converge:
it hides the failure rather than fixing it.

If Newton diverges, the model is telling you something. Check, in order:
whether the thrust available can meet the thrust required at all (a slot
provider models ONE engine; the mission scales by the architecture's
engine count), whether a surrogate's training envelope covers the
conditions the mission asks for, and whether the surrogate was trained on
physically admissible data (`hangar.omd.diagnostics.check_deck`).

`hangar.omd.diagnostics.find_unsolved_implicit(prob)` lists any balance no
solver can reach; it needs only `final_setup()`, so it answers in about a
second on a plan that takes an hour to run.
