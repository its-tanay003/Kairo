# KAIRO: Security Model, Scope Contracts & Sandbox Isolation

> **Cryptographic Scope Boundaries, Zero-Trust Execution Gates, & Sandbox Containment**  
> **Target Release**: KAIRO v4.0.0

---

## Table of Contents

1. [Threat Model & Safety Philosophy](#1-threat-model--safety-philosophy)
2. [The Scope Contract Specification](#2-the-scope-contract-specification)
3. [HMAC-SHA256 Cryptographic Gate](#3-hmac-sha256-cryptographic-gate)
4. [CIDR Matching & Excluded Host Gates](#4-cidr-matching--excluded-host-gates)
5. [Kali Linux Guest Sandbox Isolation](#5-kali-linux-guest-sandbox-isolation)
6. [Active Resource Caps & Forensics](#6-active-resource-caps--forensics)
7. [Emergency Killswitches & Instant Snapshot Revert](#7-emergency-killswitches--instant-snapshot-revert)

---

## 1. Threat Model & Safety Philosophy

Autonomous cyber agents possess immense potential for defensive auditing, but unconstrained autonomy carries critical operational risks:
- **Scope Creep**: An autonomous model could misinterpret a goal and probe unapproved IP addresses or external production systems.
- **Service Disruption**: Aggressive scanning tools could overload fragile network devices or default gateways.
- **Payload Escape**: Malicious artifacts could compromise the host operating system if executed unsafely.

KAIRO resolves these risks with a **Zero-Trust Safety Perimeter**:
1. *No execution without an authorized cryptographic Scope Contract.*
2. *Every IP target is validated against permitted CIDR blocks prior to process creation.*
3. *All execution happens inside an isolated, disposable virtualization sandbox.*
4. *All actions generate an immutable, tamper-evident forensic log.*

---

## 2. The Scope Contract Specification

A **Scope Contract** is a signed JSON payload defining the operational boundaries for a mission:

```json
{
  "target": "192.168.1.0/24",
  "allowed_cidrs": [
    "192.168.1.0/24",
    "10.0.0.0/8"
  ],
  "excluded_hosts": [
    "192.168.1.1",
    "10.0.0.1"
  ],
  "max_tier": 2,
  "expires_at": "2026-10-14T00:00:00Z",
  "operator_id": "operator_local_admin",
  "signature": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

---

## 3. HMAC-SHA256 Cryptographic Gate

Before any tool execution adapter is spawned, the Orchestrator evaluates the contract signature using a shared platform secret:

```python
import hmac
import hashlib
import json

def verify_scope_contract(contract: dict, secret: bytes) -> bool:
    received_sig = contract.get("signature", "")
    # Generate canonical serialization excluding signature key
    canonical_data = json.dumps({k: v for k, v in contract.items() if k != "signature"}, sort_keys=True)
    expected_sig = hmac.new(secret, canonical_data.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_sig, expected_sig)
```

If the signature fails or the contract has expired, process creation is denied immediately, and an unhandled authorization error is logged to the forensic database.

---

## 4. CIDR Matching & Excluded Host Gates

Every target address supplied by the agent or operator is parsed through Python's `ipaddress` library:

```python
import ipaddress

def is_target_in_scope(target_ip: str, contract: dict) -> bool:
    ip = ipaddress.ip_address(target_ip)

    # 1. Check excluded hosts (Gateways, DNS, Firewalls)
    for excluded in contract.get("excluded_hosts", []):
        if ip == ipaddress.ip_address(excluded):
            return False

    # 2. Verify target belongs to an authorized CIDR block
    for cidr in contract.get("allowed_cidrs", []):
        if ip in ipaddress.ip_network(cidr):
            return True

    return False
```

Attempts to probe `192.168.1.1` (the gateway) or external IPs (`8.8.8.8`) are blocked deterministically.

---

## 5. Kali Linux Guest Sandbox Isolation

Execution takes place inside a disposable virtual machine running headless Kali Linux:
- **Network Isolation**: The VM is attached exclusively to a VirtualBox Host-Only network (`vboxnet0`, `192.168.56.0/24`) and a monitored test laboratory bridge. The host operating system's primary network interfaces are completely inaccessible to the guest.
- **REST Communication**: The host communicates with the guest exclusively over a hardened FastAPI worker agent listening on `192.168.56.10:9999`.
- **Non-Root Execution**: By default, commands execute under the unprivileged `kali` user account unless explicitly authorized by a Tier 2 ToolSpec.

---

## 6. Active Resource Caps & Forensics

To prevent memory leaks, fork bombs, or hung processes:
- **cgroup Resource Limits**: Each process created by the worker agent is placed into a dedicated Linux cgroup with hard limits on CPU (`cpu_limit_pct`) and memory (`memory_cap_mb`).
- **Timeout Watchdog**: If a process exceeds its ToolSpec `timeout_s`, the supervisor sends `SIGTERM` followed by a hard `SIGKILL` within 2 seconds.
- **Forensic Preservation**: Standard output, standard error, generated files, and network connection states are collected and stored in `events/events.db` before process termination.

---

## 7. Emergency Killswitches & Instant Snapshot Revert

KAIRO provides two instant safety killswitches:
1. **Interactive UI Emergency Stop**: Clicking `Stop` or `SIGKILL` in the Console drawer sends an immediate termination signal across the WebSocket Gateway.
2. **Instant VM Snapshot Revert**: If an exploit causes a kernel panic or persistent system instability in the sandbox, the VM is instantly reverted to its clean baseline snapshot in under 3 seconds using `VBoxManage snapshot "Kali-Worker" restore "baseline_clean"`.
