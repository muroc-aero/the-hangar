# Task: Size a Single-Spool Turbojet at Sea-Level Static

Run a pyCycle turbojet design-point analysis using the omd pipeline.

## Requirements

- Engine: single-spool turbojet (compressor, burner, turbine, nozzle)
- Compressor PR: 13.5, efficiency: 0.83
- Turbine efficiency: 0.86
- Shaft speed: 8070 rpm
- Thermo method: CEA (chemical equilibrium)
- Design point: sea-level static (alt=0 ft, MN~0)
- Thrust target: 11,800 lbf
- T4 target: 2,370 degR

## Steps

1. Create a plan YAML with component type `pyc/TurbojetDesign`
2. Set operating points: alt=0.0, MN=0.000001, Fn_target=11800.0, T4_target=2370.0
3. Set engine config: comp_PR=13.5, comp_eff=0.83, turb_eff=0.86, Nmech=8070.0, thermo_method=CEA
4. Run via: `omd-cli run plan.yaml --mode analysis`

## Expected outputs

- Net thrust (Fn) matching the 11,800 lbf target
- TSFC in the range 0.8-1.5 lbm/hr/lbf (typical turbojet)
- OPR equal to compressor PR (13.5, single-spool)
- Gross thrust (Fg) slightly above net thrust (ram drag is near zero at SLS)

## Deliverables

1. The plan YAML file
2. Run results showing Fn, TSFC, OPR, Fg
3. Interpretation of whether the results are physically reasonable
