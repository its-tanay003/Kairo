# KAIRO: ToolSpec Authoring & 7-Gate Conformance Guide

> **Developer Guide for Building, Certifying, and Registering Autonomous Security Tools**  
> **ToolSpec Specification**: v2.1.0 (16-Field Declarative Standard)

---

## Table of Contents

1. [Introduction to ToolSpec](#1-introduction-to-toolspec)
2. [The 16-Field ToolSpec Schema Specification](#2-the-16-field-toolspec-schema-specification)
3. [Safety Privilege Tiers (Tier 1 vs Tier 2 vs Tier 3)](#3-safety-privilege-tiers-tier-1-vs-tier-2-vs-tier-3)
4. [ToolSpec SDK & CLI Scaffolding (`/sdk`)](#4-toolspec-sdk--cli-scaffolding-sdk)
5. [Authoring Execution Adapters (Python & Bash)](#5-authoring-execution-adapters-python--bash)
6. [The 7-Gate Conformance Engine](#6-the-7-gate-conformance-engine)
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

Every ToolSpec YAML file stored in [`registry/`](file:///c:/New%20Volume%20(D)/dev/registry) must contain exactly these 16 fields:

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string` | Yes | Unique reverse-DNS identifier (e.g. `nmap.scan.v1`) |
| `name` | `string` | Yes | Human-readable tool title |
| `version` | `string` | Yes | Semantic version (e.g. `1.0.0`) |
| `description` | `string` | Yes | Plain-language functional overview used for semantic matching |
| `category` | `string` | Yes | Operational category (`recon`, `discovery`, `exploit`, `audit`) |
| `tier` | `integer` | Yes | Safety tier: `1` (Safe Read-Only), `2` (Active CLI), `3` (GUI) |
| `runner` | `string` | Yes | Execution environment: `python` or `bash` |
| `entrypoint` | `string` | Yes | File path to execution adapter script |
| `timeout_s` | `integer` | Yes | Hard execution cutoff in seconds |
| `memory_cap_mb` | `integer` | Yes | Max RAM allocation before SIGKILL |
| `cpu_limit_pct` | `integer` | Yes | Max cgroup CPU utilization threshold |
| `parameters` | `object` | Yes | JSON Schema describing input arguments |
| `required_args`| `array` | Yes | List of mandatory parameter keys |
| `output_schema`| `object` | Yes | JSON Schema of structured observations |
| `author` | `string` | Yes | Organization or maintainer |
| `license` | `string` | Yes | Open-source or enterprise license |

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

## 6. The 7-Gate Conformance Engine

Before any tool is accepted into the production registry, it must pass all 7 automated conformance gates implemented in [`sdk/conformance.py`](file:///c:/New%20Volume%20(D)/dev/sdk):

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
