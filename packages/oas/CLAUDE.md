# muroc-oas — OpenAeroStruct MCP Server

This package wraps OpenAeroStruct as an MCP tool server using FastMCP.

## Key constraints

- `num_y` must always be odd (3, 5, 7, 9, ...)
- Structural analysis requires `fem_model_type="tube"` or `"wingbox"` with material properties
- Control-point arrays are ordered root-to-tip
- Physics validation runs on every analysis response
