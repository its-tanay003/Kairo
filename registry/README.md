# /registry - YAML ToolSpec Definitions & Loaders

Contains declarative definitions for all agent tools following the blueprint standard. Every tool definition is validated against the formal JSON Schema (`registry/schema/toolspec.schema.json`) on startup. Malformed specs are rejected at load time, not at execution time.

## Exact 16-Field Blueprint Schema

Every ToolSpec YAML definition strictly implements all 16 specification fields:

```yaml
id: string                    # Unique tool identifier (e.g. shell.run.v1, kali.exec.v1)
binary: string                # Executable command path, name, or internal handler
category: string              # Classification (execution, sandbox_execution, utility, diagnostic)
capabilities: [string]        # Capability tokens declaring functionality
inputs: object                # Parameter definitions with types, descriptions, defaults, requirements
outputs: object               # Return attributes, output formats, and artifacts
side_effects: [string]        # Declared external side effects (process creation, disk/network)
privilege: string             # Required privilege level (user, root, admin, elevated, kernel, guest)
gui: boolean | object         # GUI interaction requirement or display metadata
parser: string | object       # Output parser strategy (raw_stream, json_stream, plain_text)
prerequisites: [string]       # Runtime packages, host binaries, or environment capabilities
docs: string | object         # Embedded reference documentation, usage guide, and examples
success_signals: object       # Exit codes, patterns, and indicators of successful execution
failure_signals: object       # Failure codes, timeout conditions, and error patterns
rollback: string | object     # Rollback strategy, compensating action, or snapshot revert
version_compatibility: obj    # Supported agent versions and OS matrix
```

## Load-Time JSON Schema Validation

Both the Python and TypeScript loaders validate each YAML spec against `registry/schema/toolspec.schema.json` upon initialization (`strict=True` by default):

- **Fail-Fast Startup**: Any missing blueprint field, invalid type, or schema violation raises `ToolSpecValidationError` immediately at startup.
- **Python**:
  ```python
  from registry.loader import ToolRegistry, ToolSpecValidationError
  reg = ToolRegistry() # Validates on startup
  spec = reg.get("shell.run.v1")
  ```
- **TypeScript**:
  ```typescript
  import { ToolRegistry, ToolSpecValidationError } from "../registry/loader";
  const reg = new ToolRegistry(); // Validates on startup
  const spec = reg.get("shell.run.v1");
  ```

## Automated Verification Tests
- `python -m pytest test_toolspec_registry.py -v` (Full schema compliance & load-time rejection testing)
- `npx tsx test_registry_ts.ts` (TypeScript loader verification)
