-- Seed the 6 in-scope laboratory methods (spec section 21) into lab.method_definition.
-- Versioned configuration: stable code, version, standard, calculation package,
-- and schema placeholders. The input/validation/result schemas are minimal but
-- real JSONB documents - they get enriched when the calculation engine lands.
--
-- Idempotent: ON CONFLICT (method_code, method_version) does nothing.

INSERT INTO lab.method_definition (
    method_definition_id, method_code, method_version, test_type,
    method_name, standard_body, standard_reference, standard_edition,
    calculation_package, calculation_package_version,
    input_schema, validation_schema, result_schema, ags_mapping_profile,
    effective_from, active, created_at, created_by
)
VALUES
    (gen_random_uuid(), 'PSD', 1, 'PSD',
     'Grain size analysis (sieve + hydrometer)', 'BIS', 'IS 2720', 'Part 4',
     'psd_engine', '1.0.0',
     '{"rows": ["size", "tare", "tareRet", "gratType"]}'::jsonb,
     '{"checks": ["percent_bounds", "mass_balance"]}'::jsonb,
     '{"outputs": ["percent_passing", "percent_retained"]}'::jsonb,
     '{"groups": ["GRAG", "GRAT"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'PARTICLE_DENSITY', 1, 'PARTICLE_DENSITY',
     'Particle density and specific gravity (pycnometer)', 'BIS', 'IS 2720', 'Part 3',
     'particle_density_engine', '1.0.0',
     '{"rows": ["trial", "m1", "m2", "m3", "m4", "temp", "use"]}'::jsonb,
     '{"checks": ["gs_range", "repeatability"]}'::jsonb,
     '{"outputs": ["specific_gravity", "particle_density"]}'::jsonb,
     '{"groups": ["LPDN"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'ATTERBERG', 1, 'ATTERBERG',
     'Atterberg limits (liquid + plastic)', 'BIS', 'IS 2720', 'Part 5',
     'atterberg_engine', '1.0.0',
     '{"rows": ["blows", "containerMass", "wetContainer", "dryContainer", "use"], "rows2": ["containerMass", "wetContainer", "dryContainer"]}'::jsonb,
     '{"checks": ["flow_curve_fit", "pi_non_negative"]}'::jsonb,
     '{"outputs": ["liquid_limit", "plasticity_index", "flow_index"]}'::jsonb,
     '{"groups": ["LLPL"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'SHRINKAGE_LIMIT', 1, 'SHRINKAGE_LIMIT',
     'Shrinkage limit and ratio', 'BIS', 'IS 2720', 'Part 6',
     'shrinkage_engine', '1.0.0',
     '{"rows": ["trial", "wetMass", "dryMass", "wetVol", "dryVol"]}'::jsonb,
     '{"checks": ["volume_positive"]}'::jsonb,
     '{"outputs": ["shrinkage_limit", "shrinkage_ratio"]}'::jsonb,
     '{"groups": ["LSLT"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'TRIAXIAL_UU', 1, 'TRIAXIAL_UU',
     'Undrained undrained triaxial (UU)', 'BIS', 'IS 2720', 'Part 11',
     'triaxial_uu_engine', '1.0.0',
     '{"rows": ["spec", "dia", "length", "cell", "q", "strain", "mode"]}'::jsonb,
     '{"checks": ["dia_positive", "cu_half_q_uu_only"]}'::jsonb,
     '{"outputs": ["cu", "failure_mode"]}'::jsonb,
     '{"groups": ["TRIG", "TRIT"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'CONSOLIDATION', 1, 'CONSOLIDATION',
     'One-dimensional consolidation (oedometer)', 'BIS', 'IS 2720', 'Part 15',
     'consolidation_engine', '1.0.0',
     '{"rows": ["stage", "direction", "stress", "eStart", "eEnd"]}'::jsonb,
     '{"checks": ["stage_order", "stress_positive"]}'::jsonb,
     '{"outputs": ["mv", "cv", "permeability"]}'::jsonb,
     '{"groups": ["CONG", "CONS"]}'::jsonb,
     '2026-01-01', true, now(), 'seed')

ON CONFLICT (method_code, method_version) DO NOTHING;
