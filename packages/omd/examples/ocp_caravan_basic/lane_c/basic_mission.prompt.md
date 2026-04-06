# Caravan Basic Mission

Run a basic three-phase mission analysis for a Cessna 208 Caravan.

Use `omd-cli run` with the plan at `lane_b/basic_mission/plan.yaml`.

```bash
omd-cli run packages/omd/examples/ocp_caravan_basic/lane_b/basic_mission/plan.yaml
```

Expected results:
- Fuel burn: ~165 kg
- OEW: ~2430 kg (may vary by ~3% due to weight model differences)
- MTOW: 3970 kg (fixed input)
