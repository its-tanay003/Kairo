# Kairo ToolSpec SDK & Third-Party Extension Framework

The **Kairo ToolSpec SDK** enables security engineers, red teams, and third-party developers to author, package, test, and certify custom security tools for autonomous orchestration by Kairo **without modifying core orchestrator or gateway code**.

---

## 1. Architecture Overview

Every tool in Kairo consists of three interconnected layers defined in the SDK:

```text
┌────────────────────────────────────────────────────────┐
│                   ToolSpec (.yaml)                     │
│  - 16 Core Blueprint Fields                            │
│  - Capabilities, Inputs, Outputs, Side Effects         │
│  - Rollback Strategy, Signals, Schema Types            │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│             BaseToolAdapter (Python)                   │
│  - Inherits from orchestrator.adapters.base.ToolAdapter│
│  - Implements build_args(inputs) -> list[str]          │
│  - Implements parse(stdout, stderr, code, meta)        │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│             BaseToolParser (Python)                    │
│  - Extracts structured findings, hosts, technologies   │
│  - Normalizes facts for cognitive Observer/Critic/LLM  │
└────────────────────────────────────────────────────────┘
```

### Zero Core Modification Guarantee

The SDK interfaces with Kairo via dynamic runtime bridges:

- `sdk.registry_bridge.register_adapter(adapter_cls)` injects third-party adapters into `adapter_registry` dynamically.
- `registry.loader.ToolRegistry.reload()` dynamically ingests new `.yaml` specifications and validates them against the JSON schema.
- Third-party packages can be dropped into `sdk/tools/` or packaged as standalone Python wheels.

---

## 2. CLI Generator (`create-toolspec`)

The SDK provides an automated scaffolding CLI generator:

```bash
# Using the CLI runner
python -m sdk create-toolspec my-tool.scan.v1 --category recon --binary mytool

# Or using the root wrapper
python create_toolspec.py my-tool.scan.v1 --category recon --binary mytool
# Or on Windows
create-toolspec.bat my-tool.scan.v1 --category recon --binary mytool
```

### Generated Package Structure

```text
sdk/tools/my_tool_scan_v1/
├── __init__.py
├── my_tool_scan_v1_adapter.py      # Adapter class inheriting from BaseToolAdapter
├── my_tool_scan_v1_parser.py       # Parser extracting structured facts
├── test_my_tool_scan_v1_conformance.py # Automated test verifying 7 gates
└── README.md                       # Tool documentation & usage guide

registry/tools/
└── my_tool_scan_v1.yaml            # 16-field blueprint schema definition
```

---

## 3. The 7-Gate Conformance Engine ("TRUSTED" Certification)

Before any third-party ToolSpec can be executed autonomously by Kairo's Planner, Critic, or VM Execution Plane, it must pass the **7 Conformance Gates** enforced by `sdk.conformance.ToolSpecConformanceRunner`:

| Gate | Name | Requirement |
| :--- | :--- | :--- |
| **Gate 1** | **Blueprint 16-Field JSON Schema** | All 16 fields (`id`, `binary`, `category`, `capabilities`, `inputs`, `outputs`, `side_effects`, `privilege`, `gui`, `parser`, `prerequisites`, `docs`, `success_signals`, `failure_signals`, `rollback`, `version_compatibility`) validated by `toolspec.schema.json`. |
| **Gate 2** | **Adapter Implementation Contract** | Class inherits from `ToolAdapter`, defines non-empty `tool_id` matching YAML, and implements callable `build_args` and `parse` methods. |
| **Gate 3** | **Argument Compilation & Safety** | `build_args(inputs)` accepts arbitrary valid inputs and returns a strictly typed `list[str]` with non-empty command arguments. |
| **Gate 4** | **Parser Determinism & Error Handling** | `parse()` returns a structured dictionary for both successful outputs and failed execution envelopes (`stderr`, non-zero exit codes) without unhandled exceptions. |
| **Gate 5** | **Observer Fact Normalization** | Execution outputs integrate cleanly with `Observer.observe()`, populating standard `ObservationFact` data (hosts, ports, technologies, vulnerabilities, etc.). |
| **Gate 6** | **Scope Contract Boundary Compliance** | Tool defines explicit target properties (`target`, `domain`, `host`, `url`, `path`) and adheres to CIDR/subnet boundaries evaluated via `is_target_in_scope`. |
| **Gate 7** | **Operational Safety Bounds** | Execution timeout $\le 300,000\text{ms}$ (5 minutes), privilege token is authorized (`user`, `root`, `admin`), explicit rollback strategy is declared, and failure signals are mapped. |

When all 7 gates pass, the SDK issues an attestation with cryptographic SHA-256 digests of both the YAML specification and adapter source code, granting **`STATUS: TRUSTED`**.

### Running Conformance Verification via CLI

```bash
python -m sdk verify-toolspec "registry/tools/my_tool_scan_v1.yaml"
```

Example Output:

```text
=======================================================
 🛡️  Kairo ToolSpec Conformance Certification Report
=======================================================
 Tool ID:       dnsrecon.enum.v1
 Version:       1.0.0
 Spec SHA-256:  72ec2800ab757efa...
 Adapter SHA:   191f931f308e12f0...
 Gates Passed:  7/7 (100.0%)
-------------------------------------------------------
 ✅ Gate 1: Blueprint 16-Field JSON Schema: All 16 core blueprint fields valid
 ✅ Gate 2: Adapter Implementation Contract: Adapter adheres to standard execution contract
 ✅ Gate 3: Argument Compilation & Parameter Safety: CLI arguments built and typed safely
 ✅ Gate 4: Output Parser Determinism & Error Handling: Parser deterministically handles success and failure envelopes
 ✅ Gate 5: Observation Fact Normalization (Observer Integration): Observer parses and normalizes structured facts
 ✅ Gate 6: Scope Contract Boundary Compliance: Target attributes interface cleanly with Scope Contract verification
 ✅ Gate 7: Operational Safety & Timeout Bounds: Timeout <= 300s, privilege valid, rollback and failure signals specified
=======================================================
 🏆 STATUS: TRUSTED (Certified for Autonomous Orchestration)
=======================================================
```

---

## 4. Reference Implementations (3 New Tools)

The SDK was validated by authoring and certifying three completely new tools not previously touched in Kairo:

### 1. `dnsrecon.enum.v1` (DNS Reconnaissance & Zone Transfer)

- **Binary**: `dnsrecon`
- **Category**: `recon`
- **Adapter**: [DnsreconEnumV1Adapter](file:///c:/New%20Volume%20(D)/dev/sdk/tools/dnsrecon_enum_v1/dnsrecon_enum_v1_adapter.py)
- **Parser**: [DnsreconEnumV1Parser](file:///c:/New%20Volume%20(D)/dev/sdk/tools/dnsrecon_enum_v1/dnsrecon_enum_v1_parser.py)
- **Features**: Extracts A, NS, MX, TXT, SOA records, detects DNS zone transfer vulnerabilities, normalizes discovered hosts.
- **Status**: `TRUSTED` (Score: 100.0%)

### 2. `wpscan.audit.v1` (WordPress CMS Security Auditor)

- **Binary**: `wpscan`
- **Category**: `web`
- **Adapter**: [WpscanAuditV1Adapter](file:///c:/New%20Volume%20(D)/dev/sdk/tools/wpscan_audit_v1/wpscan_audit_v1_adapter.py)
- **Parser**: [WpscanAuditV1Parser](file:///c:/New%20Volume%20(D)/dev/sdk/tools/wpscan_audit_v1/wpscan_audit_v1_parser.py)
- **Features**: Identifies WordPress core version, enumerates vulnerable plugins/themes, extracts user logins and CVE findings.
- **Status**: `TRUSTED` (Score: 100.0%)

### 3. `trivy.fs.v1` (DevSecOps Filesystem & Dependency Scanner)

- **Binary**: `trivy`
- **Category**: `analysis`
- **Adapter**: [TrivyFsV1Adapter](file:///c:/New%20Volume%20(D)/dev/sdk/tools/trivy_fs_v1/trivy_fs_v1_adapter.py)
- **Parser**: [TrivyFsV1Parser](file:///c:/New%20Volume%20(D)/dev/sdk/tools/trivy_fs_v1/trivy_fs_v1_parser.py)
- **Features**: Analyzes local filesystems and repository dependencies for known CVEs, exposed secrets, and misconfigurations in JSON/table formats.
- **Status**: `TRUSTED` (Score: 100.0%)

---

## 5. Running SDK Automated Tests

Run the complete test suite verifying generator scaffolding, dynamic bridging, observer fact normalization, and all conformance gates:

```bash
python -m pytest test_toolspec_sdk.py -v
```
