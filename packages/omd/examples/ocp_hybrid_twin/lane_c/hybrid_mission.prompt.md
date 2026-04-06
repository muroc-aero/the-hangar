# Hybrid Twin Mission

Run a series-hybrid electric mission for a King Air C90GT.

```bash
omd-cli run packages/omd/examples/ocp_hybrid_twin/lane_b/hybrid_mission/plan.yaml
```

Expected results:
- Fuel burn: varies with hybridization
- TOFL: takeoff field length in feet
- OEW: ~2600 kg
- MTOW: 4581 kg (fixed input)
