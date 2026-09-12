"""The OAS wing-mass example mission (fixed-profile, 1800 nmi).

Copied verbatim from upstream Aviary's
``aviary/models/external_subsystems/open_aero_struct/run_OAS_wing_mass_example.py``
(v1.0.1) -- the mission that upstream pairs with its OAS wing-mass
external subsystem: 3 phases (two climbs + descent), mach/altitude
profiles pinned (``*_optimize: False``), no takeoff/landing,
``optimize_mass: True``. SLSQP converges it (measured in
docs/aviary-oas-integration-plan.md, WP1).

Kept as a hangar config module (single copy) because upstream ships it
inline in a script that runs on import; the Lane A oracle scripts and the
``oas_wing_example`` mission template both read it from here.
"""

phase_info = {
    'climb_1': {
        'subsystem_options': {'aerodynamics': {'method': 'computed'}},
        'user_options': {
            'num_segments': 5,
            'order': 3,
            'distance_solve_segments': False,
            'mach_optimize': False,
            'mach_polynomial_order': 1,
            'mach_initial': (0.2, 'unitless'),
            'mach_final': (0.72, 'unitless'),
            'mach_bounds': ((0.18, 0.74), 'unitless'),
            'altitude_optimize': False,
            'altitude_polynomial_order': 1,
            'altitude_initial': (0.0, 'ft'),
            'altitude_final': (32000.0, 'ft'),
            'altitude_bounds': ((0.0, 34000.0), 'ft'),
            'throttle_enforcement': 'path_constraint',
            'time_initial': (0.0, 'min'),
            'time_duration_bounds': ((64.0, 192.0), 'min'),
        },
        'initial_guesses': {'time': ([0, 128], 'min')},
    },
    'climb_2': {
        'subsystem_options': {'aerodynamics': {'method': 'computed'}},
        'user_options': {
            'num_segments': 5,
            'order': 3,
            'mach_optimize': False,
            'mach_polynomial_order': 1,
            'mach_initial': (0.72, 'unitless'),
            'mach_final': (0.72, 'unitless'),
            'mach_bounds': ((0.7, 0.74), 'unitless'),
            'altitude_optimize': False,
            'altitude_polynomial_order': 1,
            'altitude_initial': (32000.0, 'ft'),
            'altitude_final': (34000.0, 'ft'),
            'altitude_bounds': ((23000.0, 38000.0), 'ft'),
            'throttle_enforcement': 'boundary_constraint',
            'time_initial_bounds': ((64.0, 192.0), 'min'),
            'time_duration_bounds': ((56.5, 169.5), 'min'),
        },
        'initial_guesses': {'time': ([128, 113], 'min')},
    },
    'descent_1': {
        'subsystem_options': {'aerodynamics': {'method': 'computed'}},
        'user_options': {
            'num_segments': 5,
            'order': 3,
            'mach_optimize': False,
            'mach_polynomial_order': 1,
            'mach_initial': (0.72, 'unitless'),
            'mach_final': (0.36, 'unitless'),
            'mach_bounds': ((0.34, 0.74), 'unitless'),
            'altitude_optimize': False,
            'altitude_polynomial_order': 1,
            'altitude_initial': (34000.0, 'ft'),
            'altitude_final': (500.0, 'ft'),
            'altitude_bounds': ((0.0, 38000.0), 'ft'),
            'throttle_enforcement': 'path_constraint',
            'time_initial_bounds': ((120.5, 361.5), 'min'),
            'time_duration_bounds': ((29.0, 87.0), 'min'),
        },
        'initial_guesses': {'time': ([241, 58], 'min')},
    },
    'post_mission': {
        'include_landing': False,
        'constrain_range': True,
        'target_range': (1800.0, 'nmi'),
    },
    'pre_mission': {'include_takeoff': False, 'optimize_mass': True},
}
