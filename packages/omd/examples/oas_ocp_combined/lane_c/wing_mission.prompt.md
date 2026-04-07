# OAS Wing Aero + OCP Caravan Mission (Composite)

Run a composite analysis with an OAS VLM wing analysis at cruise alongside
an OCP Caravan basic mission, both in a single omd Problem.

```bash
omd-cli run packages/omd/examples/oas_ocp_combined/lane_b/wing_mission/plan.yaml
```

This demonstrates multi-component composition: two independent analysis tools
(OpenAeroStruct and OpenConcept) running side-by-side in one OpenMDAO Problem.

Expected results:
- Wing CL: ~0.270
- Wing CD: ~0.0277
- Wing L/D: ~9.75
- Mission fuel burn: ~171 kg
- OEW: ~2267 kg
- MTOW: 3970 kg (fixed input)

The two components run independently here (no connections between them).
To connect OAS drag output to OCP mission drag input, add a `connections`
section to the plan YAML.
