# Caravan Full Mission

Run a full mission analysis for a Cessna 208 Caravan with balanced-field takeoff.

```bash
omd-cli run packages/omd/examples/ocp_caravan_full/lane_b/full_mission/plan.yaml
```

Expected results:
- Fuel burn: ~171 kg
- TOFL: takeoff field length in feet
- OEW: ~2267 kg
- MTOW: 3970 kg (fixed input)
