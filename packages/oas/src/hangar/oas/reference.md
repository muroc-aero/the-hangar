# OpenAeroStruct MCP — quick reference

## Workflow order (mandatory)
  create_surface → run_aero_analysis | run_aerostruct_analysis
                 → compute_drag_polar | compute_stability_derivatives
                 → run_optimization
  reset  (clears all state)

## create_surface — key parameters
  name          str      Surface identifier used in all other tools
  wing_type     str      "rect" (flat, no twist) | "CRM" (transport planform with twist)
  span          float    Full wingspan in metres (default 10.0)
  root_chord    float    Root chord in metres (default 1.0)
  num_x         int      Chordwise nodes, >= 2 (default 2)
  num_y         int      Spanwise nodes, ODD, >= 3 (default 7)
  symmetry      bool     True = model half-span (recommended, default True)
  sweep         float    Leading-edge sweep, degrees (default 0)
  dihedral      float    Dihedral angle, degrees (default 0)
  taper         float    Taper ratio tip/root chord (default 1.0 = no taper)
  twist_cp      float[]  Twist control points, degrees, root-to-tip (None = zero twist)
  t_over_c_cp   float[]  Thickness/chord control points, root-to-tip (default [0.15])
  with_viscous  bool     Include viscous drag (default True)
  with_wave     bool     Include wave drag (default False)
  CD0           float    Zero-lift profile drag added to total (default 0.015)
  fem_model_type str|None "tube" | "wingbox" | None  — enables structural analysis
  E             float    Young's modulus, Pa (default 70e9 = Al 7075)
  G             float    Shear modulus, Pa (default 30e9 = Al 7075)
  yield_stress  float    Yield stress, Pa (default 500e6)
  safety_factor float    Safety factor on yield (default 2.5)
  mrho          float    Material density, kg/m³ (default 3000 = Al 7075)
  thickness_cp  float[]  Tube thickness control points, m, root-to-tip (default 0.1*root_chord)
  offset        float[3] [x,y,z] origin offset in metres (e.g. tail: [50,0,0])

NOTE: All *_cp arrays use ROOT-to-TIP ordering: cp[0]=root, cp[-1]=tip.
  Example: twist_cp=[-7, 0] → root=-7° (washed in), tip=0°.
  Optimised DV arrays returned by run_optimization follow the same convention.

## Typical flight conditions (cruise, ~FL350)
  velocity=248.136 m/s  Mach_number=0.84  density=0.38 kg/m³
  reynolds_number=1e6   speed_of_sound=295.4 m/s

## run_aero_analysis — returns
  CL, CD, CM, L_over_D
  surfaces.{name}.{CL, CD, CDi, CDv, CDw}

## run_aerostruct_analysis — returns (all of aero plus)
  fuelburn kg, structural_mass kg, L_equals_W (residual, 0=trimmed)
  surfaces.{name}.{failure, max_vonmises_Pa, structural_mass_kg}
  failure < 0  →  safe;  failure > 0  →  structural failure

## compute_drag_polar — returns
  alpha_deg[], CL[], CD[], CM[], L_over_D[]
  best_L_over_D.{alpha_deg, CL, CD, L_over_D}

## compute_stability_derivatives — returns
  CL_alpha (1/deg), CM_alpha (1/deg), static_margin, stability (string)
  static_margin = -CM_alpha/CL_alpha;  positive = statically stable

## run_optimization — design variable names
  twist, thickness, chord, sweep, taper, alpha
  spar_thickness, skin_thickness  (wingbox only)

## run_optimization — constraint names
  aero:        CL, CD, CM
  aerostruct:  CL, CD, CM, failure, thickness_intersects, L_equals_W

## run_optimization — objective names
  aero:        CD, CL
  aerostruct:  fuelburn, structural_mass, CD

## Artifact storage (automatic)
  Every analysis tool saves a run_id.  Use it to retrieve results later.
  Storage layout: {OAS_DATA_DIR}/{user}/{project}/{session_id}/{run_id}.json
  OAS_DATA_DIR env var controls storage root (default: ./oas_data/)
  OAS_USER env var sets user identity (default: OS login name)
  OAS_PROJECT env var sets default project per session (default: "default")
  Pass run_name="label" to tag a run; visible in list_artifacts output.
  list_artifacts(session_id?, analysis_type?, user?, project?)  list saved runs
  get_artifact(run_id, session_id?)             full metadata + results
  get_artifact_summary(run_id, session_id?)     metadata only (no payload)
  delete_artifact(run_id, session_id?)          remove permanently
  oas://artifacts/{run_id}                      resource access by run_id

## visualize — output modes
  output="inline" (default)  returns [metadata, ImageContent] — best for claude.ai
  output="file"              saves PNG to disk, returns [metadata] with file_path — CLI-friendly
  output="url"               returns [metadata] with dashboard_url + plot_url — VPS CLI
  Per-call: visualize(run_id, plot_type, output="file")
  Per-session: configure_session(visualization_output="url")

## Dashboard
  /dashboard?run_id=<id>   context-rich HTML page (flight conds, results, plots, validation)
  Local:  http://localhost:7654/dashboard?run_id=X  (no auth)
  VPS:    use visualize(run_id, output="url") to get the correct dashboard URL

## Common errors and fixes
  "num_y must be odd"           → change num_y to nearest odd number
  "missing structural props"    → re-create surface with fem_model_type="tube"
  "Surface not found"           → call create_surface first with that exact name
  "Unknown design variable"     → check spelling against the DV list above
