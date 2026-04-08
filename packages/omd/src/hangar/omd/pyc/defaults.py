"""Default parameters and initial guesses for pyCycle archetypes."""

# ---------------------------------------------------------------------------
# Flight conditions
# ---------------------------------------------------------------------------

DEFAULT_DESIGN_CONDITIONS = {
    "alt": 0.0,         # ft (sea-level static for turbojet)
    "MN": 0.000001,     # Mach (near-zero for SLS)
    "Fn_target": 11800, # lbf
    "T4_target": 2370,  # degR
}

DEFAULT_CRUISE_CONDITIONS = {
    "alt": 35000,       # ft
    "MN": 0.8,
    "Fn_target": 5800,  # lbf
    "T4_target": 3200,  # degR
}

# ---------------------------------------------------------------------------
# Turbojet
# ---------------------------------------------------------------------------

DEFAULT_TURBOJET_PARAMS = {
    "thermo_method": "CEA",  # "TABULAR" or "CEA"
    "comp_PR": 13.5,
    "comp_eff": 0.83,
    "turb_eff": 0.86,
    "Nmech": 8070.0,       # rpm
    "burner_dPqP": 0.03,
    "nozz_Cv": 0.99,
    # Element MN defaults (design point)
    "inlet_MN": 0.60,
    "comp_MN": 0.02,
    "burner_MN": 0.02,
    "turb_MN": 0.4,
}

DEFAULT_TURBOJET_DESIGN_GUESSES = {
    "FAR": 0.0175506829934,
    "W": 168.453135137,
    "turb_PR": 4.46138725662,
    "fc_Pt": 14.6955113159,
    "fc_Tt": 518.665288153,
}

DEFAULT_TURBOJET_OD_GUESSES = {
    "W": 166.073,
    "FAR": 0.01680,
    "Nmech": 8197.38,
    "fc_Pt": 15.703,
    "fc_Tt": 558.31,
    "turb_PR": 4.6690,
}

# ---------------------------------------------------------------------------
# High-bypass turbofan (HBTF)
# ---------------------------------------------------------------------------

DEFAULT_HBTF_PARAMS = {
    "thermo_method": "CEA",
    "fan_PR": 1.685,
    "fan_eff": 0.8948,
    "lpc_PR": 1.935,
    "lpc_eff": 0.9243,
    "hpc_PR": 9.369,
    "hpc_eff": 0.8707,
    "hpt_eff": 0.8888,
    "lpt_eff": 0.8996,
    "BPR": 5.105,
    "LP_Nmech": 4666.1,    # rpm
    "HP_Nmech": 14705.7,   # rpm
    "design_T4": 2857.0,   # degR
    "design_Fn": 5900.0,   # lbf
    "burner_dPqP": 0.054,
    # Duct losses
    "duct4_dPqP": 0.0048,
    "duct6_dPqP": 0.0101,
    "duct11_dPqP": 0.0051,
    "duct13_dPqP": 0.0107,
    "duct15_dPqP": 0.0149,
    # Nozzle coefficients
    "core_nozz_Cv": 0.9933,
    "byp_nozz_Cv": 0.9939,
    # Bleed fractions
    "cool1_frac_W": 0.050708,
    "cool2_frac_W": 0.020274,
    "cool3_frac_W": 0.067214,
    "cool4_frac_W": 0.101256,
    "cust_frac_W": 0.0445,
    # Inlet
    "inlet_ram_recovery": 0.9990,
}

DEFAULT_HBTF_DESIGN_GUESSES = {
    "FAR": 0.025,
    "W": 100.0,
    "lpt_PR": 4.0,
    "hpt_PR": 3.0,
    "fc_Pt": 5.2,
    "fc_Tt": 440.0,
}

DEFAULT_HBTF_OD_GUESSES = {
    "FAR": 0.02467,
    "W": 300.0,
    "BPR": 5.105,
    "lp_Nmech": 5000.0,
    "hp_Nmech": 15000.0,
    "hpt_PR": 3.0,
    "lpt_PR": 4.0,
    "fan_RlineMap": 2.0,
    "lpc_RlineMap": 2.0,
    "hpc_RlineMap": 2.0,
}

# ---------------------------------------------------------------------------
# Afterburning turbojet
# ---------------------------------------------------------------------------

DEFAULT_AB_TURBOJET_PARAMS = {
    "thermo_method": "CEA",
    "comp_PR": 13.5,
    "comp_eff": 0.83,
    "turb_eff": 0.86,
    "Nmech": 8070.0,
    "duct1_dPqP": 0.02,
    "burner_dPqP": 0.03,
    "ab_dPqP": 0.06,
    "nozz_Cv": 0.99,
    "cool1_frac_W": 0.0789,
    "cool1_frac_P": 1.0,
    "cool1_frac_work": 1.0,
    "cool2_frac_W": 0.0383,
    "cool2_frac_P": 1.0,
    "cool2_frac_work": 1.0,
    "turb_cool1_frac_P": 1.0,
    "turb_cool2_frac_P": 0.0,
    # Element MN defaults
    "inlet_MN": 0.60,
    "duct1_MN": 0.60,
    "comp_MN": 0.20,
    "burner_MN": 0.20,
    "turb_MN": 0.4,
    "ab_MN": 0.4,
}

DEFAULT_AB_TURBOJET_DESIGN_CONDITIONS = {
    "alt": 0.0,
    "MN": 0.000001,
    "Fn_target": 11800.0,
    "T4_target": 2370.0,
    "ab_FAR": 0.0,  # dry by default
}

DEFAULT_AB_TURBOJET_DESIGN_GUESSES = {
    "FAR": 0.01755078,
    "W": 168.00454616,
    "turb_PR": 4.46131867,
    "fc_Pt": 14.6959,
    "fc_Tt": 518.67,
}

DEFAULT_AB_TURBOJET_OD_GUESSES = {
    "W": 168.0,
    "FAR": 0.01755,
    "Nmech": 8070.0,
    "turb_PR": 4.4613,
}

# ---------------------------------------------------------------------------
# Single-spool turboshaft
# ---------------------------------------------------------------------------

DEFAULT_SINGLE_TURBOSHAFT_PARAMS = {
    "thermo_method": "CEA",
    "comp_PR": 13.5,
    "comp_eff": 0.83,
    "turb_eff": 0.86,
    "pt_eff": 0.9,
    "HP_Nmech": 8070.0,
    "LP_Nmech": 5000.0,
    "burner_dPqP": 0.03,
    "nozz_Cv": 0.99,
    # Element MN defaults
    "inlet_MN": 0.60,
    "comp_MN": 0.20,
    "burner_MN": 0.20,
    "turb_MN": 0.4,
}

DEFAULT_SINGLE_TURBOSHAFT_DESIGN_CONDITIONS = {
    "alt": 0.0,
    "MN": 0.000001,
    "T4_target": 2370.0,
    "pwr_target": 4000.0,    # hp
    "nozz_PR_target": 1.2,
}

DEFAULT_SINGLE_TURBOSHAFT_DESIGN_GUESSES = {
    "FAR": 0.0175506829934,
    "W": 27.265,
    "turb_PR": 3.8768,
    "pt_PR": 2.0,
    "fc_Pt": 14.69551131598148,
    "fc_Tt": 518.665288153,
}

DEFAULT_SINGLE_TURBOSHAFT_OD_GUESSES = {
    "W": 27.265,
    "FAR": 0.0175506829934,
    "HP_Nmech": 8070.0,
    "turb_PR": 3.8768,
    "pt_PR": 2.0,
    "fc_Pt": 15.703,
    "fc_Tt": 558.31,
}

# ---------------------------------------------------------------------------
# Multi-spool turboshaft
# ---------------------------------------------------------------------------

DEFAULT_MULTI_TURBOSHAFT_PARAMS = {
    "thermo_method": "CEA",
    "lpc_PR": 5.0,
    "lpc_eff": 0.89,
    "hpc_axi_PR": 3.0,
    "hpc_axi_eff": 0.89,
    "hpc_centri_PR": 2.7,
    "hpc_centri_eff": 0.88,
    "hpt_eff": 0.89,
    "lpt_eff": 0.9,
    "pt_eff": 0.85,
    "LP_Nmech": 12750.0,
    "IP_Nmech": 12000.0,
    "HP_Nmech": 14800.0,
    "lp_shaft_HPX": 1800.0,  # hp
    # Duct losses
    "inlet_ram_recovery": 1.0,
    "duct1_dPqP": 0.0,
    "icduct_dPqP": 0.002,
    "duct6_dPqP": 0.0,
    "burner_dPqP": 0.05,
    "duct43_dPqP": 0.0051,
    "itduct_dPqP": 0.0,
    "duct12_dPqP": 0.0,
    "nozzle_Cv": 0.99,
    # Bleed fractions
    "cool1_frac_W": 0.024,
    "cool2_frac_W": 0.0146,
    "cool3_frac_W": 0.1705,
    "cool4_frac_W": 0.1209,
    "hpt_cool3_frac_P": 1.0,
    "hpt_cool4_frac_P": 0.0,
    "lpt_cool1_frac_P": 1.0,
    "lpt_cool2_frac_P": 0.0,
}

DEFAULT_MULTI_TURBOSHAFT_DESIGN_CONDITIONS = {
    "alt": 28000.0,
    "MN": 0.5,
    "T4_target": 2740.0,   # degR
    "nozz_PR_target": 1.1,
}

DEFAULT_MULTI_TURBOSHAFT_DESIGN_GUESSES = {
    "FAR": 0.02261,
    "W": 10.76,
    "hpt_PR": 4.233,
    "lpt_PR": 1.979,
    "pt_PR": 4.919,
    "fc_Pt": 5.666,
    "fc_Tt": 440.0,
}

DEFAULT_MULTI_TURBOSHAFT_OD_GUESSES = {
    "FAR": 0.02135,
    "W": 10.775,
    "HP_Nmech": 14800.0,
    "IP_Nmech": 12000.0,
    "hpt_PR": 4.233,
    "lpt_PR": 1.979,
    "pt_PR": 4.919,
    "fc_Pt": 5.666,
    "fc_Tt": 440.0,
}

# ---------------------------------------------------------------------------
# Mixed-flow turbofan
# ---------------------------------------------------------------------------

DEFAULT_MIXEDFLOW_PARAMS = {
    "thermo_method": "CEA",
    "fan_PR": 3.3,
    "fan_eff": 0.8948,
    "lpc_PR": 1.935,
    "lpc_eff": 0.9243,
    "hpc_PR": 4.9,
    "hpc_eff": 0.8707,
    "hpt_eff": 0.8888,
    "lpt_eff": 0.8996,
    "LP_Nmech": 4666.1,
    "HP_Nmech": 14705.7,
    "hp_shaft_HPX": 250.0,  # hp
    # Duct losses
    "inlet_ram_recovery": 0.999,
    "inlet_duct_dPqP": 0.0107,
    "splitter_core_duct_dPqP": 0.0048,
    "lpc_duct_dPqP": 0.0101,
    "burner_dPqP": 0.054,
    "hpt_duct_dPqP": 0.0051,
    "lpt_duct_dPqP": 0.0107,
    "bypass_duct_dPqP": 0.0107,
    "mixer_duct_dPqP": 0.0107,
    "afterburner_dPqP": 0.054,
    "mixed_nozz_Cfg": 0.9933,
    # Bleed
    "cool1_frac_W": 0.050708,
    "cool1_frac_P": 0.5,
    "cool1_frac_work": 0.5,
    "cool3_frac_W": 0.067214,
    "hpt_cool3_frac_P": 1.0,
    "lpt_cool1_frac_P": 1.0,
}

DEFAULT_MIXEDFLOW_DESIGN_CONDITIONS = {
    "alt": 35000.0,
    "MN": 0.8,
    "Fn_target": 5500.0,
    "T4_target": 3200.0,    # degR (core burner)
    "T_ab_target": 3400.0,  # degR (afterburner)
    "BPR_target": 1.05,     # mixer ER
}

DEFAULT_MIXEDFLOW_DESIGN_GUESSES = {
    "FAR_core": 0.025,
    "FAR_ab": 0.025,
    "BPR": 1.0,
    "W": 100.0,
    "lpt_PR": 3.5,
    "hpt_PR": 2.5,
    "fc_Pt": 5.2,
    "fc_Tt": 440.0,
    "mixer_P_tot": 15.0,
}

DEFAULT_MIXEDFLOW_OD_GUESSES = {
    "FAR_core": 0.025,
    "FAR_ab": 0.025,
    "BPR": 2.5,
    "W": 50.0,
    "HP_Nmech": 14000.0,
    "LP_Nmech": 4000.0,
    "fc_Pt": 5.2,
    "fc_Tt": 440.0,
    "mixer_P_tot": 15.0,
    "hpt_PR": 2.0,
    "lpt_PR": 4.0,
    "fan_RlineMap": 2.0,
    "lpc_RlineMap": 2.0,
    "hpc_RlineMap": 2.0,
}

# ---------------------------------------------------------------------------
# Archetype metadata (for result extraction and validation)
# ---------------------------------------------------------------------------

TURBOJET_META = {
    "description": "Single-spool turbojet (compressor, burner, turbine, nozzle)",
    "elements": ["fc", "inlet", "comp", "burner", "turb", "nozz", "shaft", "perf"],
    "valid_design_vars": ["comp_PR", "comp_eff", "turb_eff", "burner_dPqP"],
    "flow_stations": [
        "fc.Fl_O", "inlet.Fl_O", "comp.Fl_O",
        "burner.Fl_O", "turb.Fl_O", "nozz.Fl_O",
    ],
    "compressors": ["comp"],
    "turbines": ["turb"],
    "burners": ["burner"],
    "shafts": ["shaft"],
    "nozzles": ["nozz"],
}
