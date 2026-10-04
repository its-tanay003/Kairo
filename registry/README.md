# /registry - YAML ToolSpec Definitions & Loader

Contains declarations for all agent tools following the declarative ToolSpec standard.

## ToolSpec Schema

```yaml
id: string          # Unique tool identifier (e.g. hello_world)
name: string        # Human-readable display name
version: string     # Semantic version (e.g. 1.0.0)
description: string # Description of capabilities and behavior
category: string    # Diagnostic, utility, system, etc.
parameters:         # JSON-schema compatible parameter spec
  type: object
  properties: ...
  required: [...]
timeout_ms: integer # Max execution budget in milliseconds
metadata:           # Custom tags, authors, sandbox flags
```

## Loaders
- **Python**: `from registry.loader import ToolRegistry; reg = ToolRegistry(); tool = reg.get("hello_world")`
- **TypeScript**: `import { ToolRegistry } from "../registry/loader";`
