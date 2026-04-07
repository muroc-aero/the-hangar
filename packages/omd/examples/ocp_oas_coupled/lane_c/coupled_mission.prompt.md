# Task: Caravan Mission with VLM Drag

Run a Cessna 208 Caravan basic mission (climb/cruise/descent) using
VLM-based drag instead of the default parabolic polar. The VLM drag
should come from OpenAeroStruct via the slot system in an OCP mission
component.

## Requirements

- Aircraft: Caravan (use the built-in template)
- Propulsion: single turboprop
- Mission: 250 NM range, 18,000 ft cruise altitude
- Drag model: replace the default PolarDrag with the `oas/vlm` slot
  provider so that drag is computed from wing geometry via VLM
- VLM mesh: num_x=2, num_y=7, num_twist=4

## Deliverables

1. Create a plan YAML for this analysis using omd-cli
2. Run the plan and report fuel burn, OEW, and MTOW
3. Record a result interpretation decision explaining whether the
   results are physically reasonable
4. Generate the provenance timeline

## Notes

- Use `/omd-cli-guide` to learn how to author plan YAML files and
  which component types and slot providers are available
- The slot config goes inside the component config, not as a separate
  top-level section
- VLMDragPolar uses a pre-trained surrogate (not live VLM per iteration),
  so expect a ~6-8 second training phase at startup
- Compare your fuel burn against the baseline Caravan mission (~165 kg
  with parabolic polar) -- the VLM result should differ because the
  drag models use different assumptions
