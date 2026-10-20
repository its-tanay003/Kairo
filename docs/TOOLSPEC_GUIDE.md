# KAIRO: ToolSpec Authoring & 7-Gate Conformance Guide

> **Developer Guide for Building, Certifying, and Registering Autonomous Security Tools**  
> **ToolSpec Specification**: v2.1.0 (16-Field Declarative Standard)

---

## Table of Contents

1. [Introduction to ToolSpec](#1-introduction-to-toolspec)
2. [The 16-Field ToolSpec Schema Specification](#2-the-16-field-toolspec-schema-specification)
3. [Safety Privilege Tiers](#3-safety-privilege-tiers)
4. [ToolSpec SDK & CLI Scaffolding (`/sdk`)](#4-toolspec-sdk--cli-scaffolding-sdk)
5. [Authoring Execution Adapters (Python & Bash)](#5-authoring-execution-adapters-python--bash)
6. [The 7-Gate Conformance & Authoritative Execution Gateway](#6-the-7-gate-conformance--authoritative-execution-gateway)
7. [Testing & Certifying New Tools with Pytest](#7-testing--certifying-new-tools-with-pytest)
8. [Example Production ToolSpec: `nmap.scan.v1`](#8-example-production-toolspec-nmapscanv1)

---

## 1. Introduction to ToolSpec

In KAIRO, autonomous models do not execute arbitrary shell strings directly. Every capability is governed by a **ToolSpec**—a declarative, versioned YAML blueprint that defines:
1. Strict parameter typing and validation regexes.
2. Resource caps (CPU percentage, memory limits, and timeouts).
3. Privilege authorization tiers.
4. Structured output parsing into typed forensic observations.

---

## 2. The 16-Field ToolSpec Schema Specification

Every ToolSpec YAML file stored in [`registry/tools/`](file:///c:/New%20Volume%20(D)/dev/registry/tools) must contain exactly all 16 specification fields defined in [`registry/schema/toolspec.schema.json`](file:///c:/New%20Volume%20(D)/dev/registry/schema/toolspec.schema.json):

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string` | Yes | Unique reverse-DNS identifier (e.g. `nmap.scan.v1`, `shell.run.v1`) |
| `binary` | `string` | Yes | Executable command path, name, or internal protocol handler |
| `category` | `string` | Yes | Operational classification (`recon`, `web_audit`, `vulnerability_scan`, `exploit`, `utility`) |
| `capabilities` | `array[string]` | Yes | Capability tokens declaring tool features (e.g. `port_scan`, `service_detection`) |
| `inputs` | `object` | Yes | Parameter schema with types, descriptions, defaults, and requirements |
| `outputs` | `object` | Yes | Schema definition of return attributes, formats, and produced artifacts |
| `side_effects` | `array[string]` | Yes | Declared external side effects (`network_scan`, `process_fork`, `disk_write`) |
| `privilege` | `string` | Yes | Required privilege token: `user`, `elevated`, `root`, `admin`, `kernel`, `guest` |
| `gui` | `boolean \| object`| Yes | GUI interaction requirement or display metadata |
| `parser` | `string \| object`| Yes | Output parser strategy (`nmap_xml`, `nikto_csv`, `json`, `plain_text`) |
| `prerequisites` | `array[string]` | Yes | Host packages, binaries, or kernel features required for execution |
| `docs` | `string \| object` | Yes | Embedded reference documentation, syntax guide, and usage examples |
| `success_signals` | `object` | Yes | Exit codes, regex patterns, and indicators of successful execution |
| `failure_signals` | `object` | Yes | Error exit codes, timeout triggers, and failure pattern matching |
| `rollback` | `string \| object` | Yes | Rollback strategy, compensating action, or VM snapshot restore |
| `version_compatibility` | `object` | Yes | Supported agent versions and OS compatibility matrix |

---

## 3. Safety Privilege Tiers

KAIRO enforces a 3-tier privilege hierarchy to prevent unintended impact on target infrastructure:

### Tier 1: Safe Read-Only (Recon & Passive Discovery)
- **Examples**: DNS resolution, WHOIS lookup, passive banner checking.
- **Safety**: No modification of remote system state. Zero risk of service disruption.
- **Scope Requirement**: Target must be within allowed CIDRs.

### Tier 2: Active CLI (Probing, Enumeration, & Verification)
- **Examples**: `nmap.scan.v1`, `nikto.web.v1`, `sqlmap.audit.v1`.
- **Safety**: Active network traffic. Strict per-command rate-limiting and timeouts.
- **Scope Requirement**: Mandatory cryptographic HMAC-SHA256 scope validation. Excluded hosts strictly forbidden.

### Tier 3: Interactive GUI (Desktop Virtualization)
- **Examples**: Burp Suite, Wireshark, Firefox browser security audits.
- **Safety**: Runs within the isolated headless Kali virtual desktop streaming over noVNC (`6080`).

---

## 4. ToolSpec SDK & CLI Scaffolding (`/sdk`)

KAIRO provides an automated CLI to generate, validate, and scaffold third-party tools:

```bash
# Generate a new Tier 2 tool blueprint
python sdk/cli.py create --id "subfinder.enum.v1" --tier 2 --category "recon" --runner "bash"
```

This creates:
- `registry/tools/subfinder.enum.v1.yaml`: Validated 16-field YAML blueprint.
- `registry/adapters/subfinder_enum_v1.sh`: Execution wrapper handling argument normalization.

---

## 5. Authoring Execution Adapters (Python & Bash)

### Python Adapter Example
```python
import json
import subprocess
import sys

def main():
    args = json.loads(sys.argv[1])
    target = args["target"]
    ports = args.get("ports", "80,443")

    cmd = ["nmap", "-sV", "-p", ports, target]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    output = {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "discovered_ports": [80, 443] if result.returncode == 0 else []
    }
    print(json.dumps(output))

if __name__ == "__main__":
    main()
```

---

## 6. The 7-Gate Conformance & Authoritative Execution Gateway

In KAIRO, tool certification occurs both statically via SDK conformance and dynamically at runtime through the authoritative [`orchestrator/execution_gateway.py`](file:///c:/New%20Volume%20(D)/dev/orchestrator/execution_gateway.py):

### 6.1 Runtime Authoritative Execution Gateway Gates

Every operational execution path (direct tool calls, DAG controller nodes, autonomous tasks, and finding verification probes) passes through `ExecutionGateway.execute()`:

```text
+---------------------------------------------------------------------------------------------------------+
|                                    ExecutionGateway 7-Gate Pipeline                                     |
+---------------------------------------------------------------------------------------------------------+
  [Gate 1] Tool Registration Check      -> Canonical ToolSpec exists in registry (127 TOOL_NOT_FOUND)
  [Gate 2] Schema & Injection Defense   -> Command injection characters blocked & defaults injected (400)
  [Gate 3] Scope Perimeter & Tier Gate  -> Target inside allowed CIDRs & tier <= max_tier (403 SCOPE_VIOLATION)
  [Gate 4] Cryptographic Operator Token -> Valid HMAC token: KAIRO-OP-<time>-<role>-<hex> (401 UNAUTHORIZED)
  [Gate 5] Broad Workflow Policy Gate   -> Cryptographic workflow token for Tier 3 tools (403 UNAPPROVED)
  [Gate 6] Isolated Adapter Execution   -> Subprocess/VM sandbox execution with timeout & real exit codes
  [Gate 7] Immutable Audit Trail        -> Complete 20-field SQLite event record written to events.db
+---------------------------------------------------------------------------------------------------------+
```

### 6.2 Static SDK Conformance Engine

Before any tool is accepted into the production registry, it must also pass all 7 automated conformance checks implemented in [`sdk/conformance.py`](file:///c:/New%20Volume%20(D)/dev/sdk):

```text
+-----------------------------------------------------------+
|               ToolSpec 7-Gate Certification               |
+-----------------------------------------------------------+
  [Gate 1] YAML Schema Integrity     -> Exactly 16 fields
  [Gate 2] Argument Validation       -> Strict JSON schema types
  [Gate 3] Sandbox Containment       -> Runs in non-root VM sandbox
  [Gate 4] Output Typing Conformance -> Parsable JSON stdout
  [Gate 5] Scope Boundary Gate       -> Targets inside allowed CIDR
  [Gate 6] Resource Cap Enforcement  -> SIGKILL on memory/timeout exceed
  [Gate 7] Forensic Audit Compliance -> Exact 20-field SQLite record
```

---

## 7. Testing & Certifying New Tools with Pytest

Verify all registered tools using the platform conformance test suite:

```bash
# Run 7-gate certification across all registered tools
python -m pytest tests/test_third_party_sdk_tool_addition.py -v
```

All 7 gates will execute in sequence, verifying that the tool adheres to memory limits, timeout cutoffs, and audit logging.

---

## 8. Example Production ToolSpec: `nmap.scan.v1`

```yaml
id: "nmap.scan.v1"
name: "Nmap Network Scanner"
version: "1.0.0"
description: "High-performance port discovery and service version enumeration."
category: "recon"
tier: 2
runner: "bash"
entrypoint: "registry/adapters/nmap_scan_v1.sh"
timeout_s: 180
memory_cap_mb: 256
cpu_limit_pct: 75
parameters:
  type: "object"
  properties:
    target:
      type: "string"
      pattern: "^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}$"
    ports:
      type: "string"
      default: "1-1000"
required_args:
  - "target"
output_schema:
  type: "object"
  properties:
    open_ports:
      type: "array"
      items: { type: "integer" }
author: "Kairo Security Core"
license: "Apache-2.0"
```
